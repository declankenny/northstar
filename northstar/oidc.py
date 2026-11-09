"""The OpenID Connect client: the authorization request, the code exchange and ID token validation. Plain functions, no web
code. See docs/design/oidc/design.md.

A sign-in is two steps. `begin_login` makes a login transaction (a random state, nonce, PKCE verifier and browser binding, kept
as hashes where they can be) and returns the address to send the browser to. `finish_login` takes the browser back: it consumes
the transaction, exchanges the code for an ID token, validates the token and hands the claims to `identities.sign_in`.

What it trusts and what it checks:
  * Only the configured issuer. Its discovery document must name that exact issuer, and every address in it must be HTTPS
    (plain HTTP only for a local host). Nothing a visitor sends picks an address.
  * The ID token is verified with the provider's own signing keys, which are fetched from the address in the discovery
    document. Only asymmetric algorithms the provider lists are accepted, never `none` and never a symmetric one. The issuer,
    the audience (and the authorized party), the expiry, the issue time and the nonce are all required to be right.
  * Only the ID token is used. There is no UserInfo request, and no access token or refresh token is kept.
  * The requests: the standard library, no redirects followed, no proxy from the environment, certificates verified, a
    time limit, and a limit on how much of an answer is read. What the provider says is never logged: a failure keeps only a
    message written here. The client secret goes only to the token endpoint and is never logged.
"""

import base64
import hashlib
import hmac
import http.client
import json
import secrets
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from northstar import clock, config, db, identities, system_properties, writer
from northstar.version import VERSION

CALLBACK_PATH = "/api/auth/oidc/callback"
SCOPE = "openid profile email"
# Asymmetric algorithms only. A symmetric one would be checked against a secret the provider and Northstar share, which an ID
# token verified with the provider's published keys never needs, and `none` is no signature at all.
ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")
DEFAULT_ALGORITHMS = ("RS256",)       # what OpenID Connect says to assume when the provider does not list any

TRANSACTION_LIFETIME = timedelta(minutes=10)
MAX_PENDING = 2000                    # logins in progress at once, so the table cannot be filled without limit
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1_000_000
MAX_TOKEN_CHARS = 16_384
MAX_KEYS = 50
LEEWAY_SECONDS = 60                   # clock difference allowed for exp, iat and nbf
METADATA_SECONDS = 3600
KEYS_SECONDS = 3600
KEYS_REFRESH_SECONDS = 60             # a key the provider rotated is looked for at most this often


class ProviderError(Exception):
    """The provider could not be used or gave a bad answer. `code` is `unreachable` (no answer, a bad status or a redirect),
    `invalid_response` (an answer that is not what the protocol says) or `invalid_token` (an ID token that is not valid).
    `reason` is for the log: it is written here and never holds the provider's own text."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class LoginError(Exception):
    """The browser came back with something that is not a login in progress: `expired` (no such transaction, or it was
    used or has run out) or `invalid` (it is not this browser's) or `busy` (too many are in progress)."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Settings:
    issuer: str
    client_id: str
    public_url: str

    @property
    def redirect_uri(self) -> str:
        return self.public_url + CALLBACK_PATH


@dataclass(frozen=True)
class Metadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    algorithms: tuple[str, ...]
    basic_auth: bool                 # the client secret goes in the Authorization header, else in the request body


@dataclass(frozen=True)
class LoginResult:
    signed_in: identities.SignedIn
    return_path: str


# -- addresses and requests --

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _address_ok(url: object) -> bool:
    """Whether an address is usable: HTTPS, or plain HTTP only for a local host, with a host, no credentials, no spaces and
    no control characters."""
    if not isinstance(url, str) or not url.isprintable() or " " in url or len(url) > 2048:
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port
    except ValueError:
        return False
    return bool(host) and parts.username is None and (parts.scheme == "https" or (parts.scheme == "http" and host in _LOCAL_HOSTS))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None             # the redirect is raised as an error instead of followed


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        _NoRedirect, urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def _request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    if not _address_ok(url):
        raise ProviderError("invalid_response", "an address from the provider is not HTTPS")
    request = urllib.request.Request(
        url, data=data, headers={"Accept": "application/json", "User-Agent": f"Northstar/{VERSION}", **(headers or {})})
    try:
        with _opener().open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as err:
        raise ProviderError("unreachable", f"the provider answered with HTTP status {err.code}") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as err:
        raise ProviderError("unreachable", f"the provider could not be reached ({type(err).__name__})") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderError("invalid_response", "the provider's answer is too large")
    return body


def _json(body: bytes) -> dict:
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):
        raise ProviderError("invalid_response", "the provider's answer is not JSON") from None
    if not isinstance(parsed, dict):
        raise ProviderError("invalid_response", "the provider's answer is not a JSON object")
    return parsed


# -- the provider's metadata and keys, kept for a while --

_lock = threading.Lock()
_metadata: dict[str, tuple[float, Metadata]] = {}
_keys: dict[str, tuple[float, KeySet]] = {}       # when they were fetched, and the keys
_monotonic = time.monotonic


def reset_cache() -> None:
    with _lock:
        _metadata.clear()
        _keys.clear()


def _fetch_metadata(issuer: str) -> Metadata:
    document = _json(_request(issuer.rstrip("/") + "/.well-known/openid-configuration"))
    if document.get("issuer") != issuer:
        raise ProviderError("invalid_response", "the discovery document names a different issuer")
    endpoints = {name: document.get(name) for name in ("authorization_endpoint", "token_endpoint", "jwks_uri")}
    if not all(_address_ok(value) for value in endpoints.values()):
        raise ProviderError("invalid_response", "the discovery document lacks an address or it is not HTTPS")
    listed = document.get("id_token_signing_alg_values_supported")
    if listed is None:
        algorithms = DEFAULT_ALGORITHMS
    elif isinstance(listed, list) and all(isinstance(name, str) for name in listed):
        algorithms = tuple(name for name in ALGORITHMS if name in listed)
    else:
        raise ProviderError("invalid_response", "the discovery document lists its signing algorithms wrongly")
    if not algorithms:
        raise ProviderError("invalid_response", "the provider signs ID tokens only with algorithms Northstar does not accept")
    methods = document.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
    if not isinstance(methods, list) or not ({"client_secret_basic", "client_secret_post"} & set(methods)):
        raise ProviderError("invalid_response", "the provider does not accept a client secret at its token endpoint")
    return Metadata(issuer, endpoints["authorization_endpoint"], endpoints["token_endpoint"], endpoints["jwks_uri"],
                    algorithms, basic_auth="client_secret_basic" in methods)


def metadata(issuer: str) -> Metadata:
    """The discovery document of the configured issuer, kept for an hour."""
    with _lock:
        found = _metadata.get(issuer)
        if found is not None and _monotonic() - found[0] < METADATA_SECONDS:
            return found[1]
    fresh = _fetch_metadata(issuer)
    with _lock:
        _metadata[issuer] = (_monotonic(), fresh)
    return fresh


def _fetch_keys(meta: Metadata) -> KeySet:
    document = _json(_request(meta.jwks_uri))
    entries = document.get("keys")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_KEYS:
        raise ProviderError("invalid_response", "the provider's key set is empty or too large")
    try:
        return KeySet.import_key_set(document)
    except (JoseError, ValueError, TypeError, KeyError):
        raise ProviderError("invalid_response", "the provider's key set cannot be read") from None


def keys(meta: Metadata, refresh: bool = False) -> KeySet:
    """The provider's signing keys, kept for an hour. `refresh` asks again because a token named a key that is not held,
    which happens when the provider rotates, but only if the keys held are at least a minute old, so a stream of bad tokens
    cannot make Northstar fetch without limit."""
    with _lock:
        found = _keys.get(meta.issuer)
        age = None if found is None else _monotonic() - found[0]
        if found is not None and age < KEYS_SECONDS and not (refresh and age >= KEYS_REFRESH_SECONDS):
            return found[1]
    fresh = _fetch_keys(meta)
    with _lock:
        _keys[meta.issuer] = (_monotonic(), fresh)
    return fresh


# -- the exchange and the token --

def exchange_code(meta: Metadata, client_id: str, secret: str, redirect_uri: str, code: str, verifier: str) -> str:
    """Trade the authorization code for an ID token, proving the PKCE verifier, and return only the ID token."""
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if meta.basic_auth:
        quoted = f"{urllib.parse.quote(client_id, safe='')}:{urllib.parse.quote(secret, safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(quoted.encode()).decode()
    else:
        form.update(client_id=client_id, client_secret=secret)
    answer = _json(_request(meta.token_endpoint, urllib.parse.urlencode(form).encode(), headers))
    token = answer.get("id_token")
    if not isinstance(token, str):
        raise ProviderError("invalid_response", "the token endpoint's answer has no ID token")
    return token


def validate_id_token(token: str, meta: Metadata, client_id: str, nonce: str, now: float | None = None) -> identities.Claims:
    """Verify the ID token's signature and claims and return the claims identity resolution reads."""
    if not isinstance(token, str) or token.count(".") != 2 or len(token) > MAX_TOKEN_CHARS:
        raise ProviderError("invalid_token", "the ID token is not a signed token")
    decoded = None
    for attempt in (0, 1):
        try:
            decoded = jwt.decode(token, keys(meta, refresh=bool(attempt)), algorithms=list(meta.algorithms))
            break
        except JoseError:
            if attempt:         # not found even after asking the provider again
                raise ProviderError("invalid_token", "the ID token's signature is not valid") from None
    claims = decoded.claims
    registry = JWTClaimsRegistry(
        now=int(time.time() if now is None else now), leeway=LEEWAY_SECONDS,
        iss={"essential": True, "value": meta.issuer}, aud={"essential": True, "value": client_id},
        exp={"essential": True}, iat={"essential": True}, sub={"essential": True},
        nonce={"essential": True, "value": nonce})
    try:
        registry.validate(claims)
    except JoseError as err:
        raise ProviderError("invalid_token", f"the ID token's claims are not valid ({type(err).__name__})") from None
    audience, authorized_party = claims["aud"], claims.get("azp")
    if (isinstance(audience, list) and len(audience) > 1 and authorized_party is None) or \
            (authorized_party is not None and authorized_party != client_id):
        raise ProviderError("invalid_token", "the ID token's authorized party is not this client")
    subject = claims["sub"]
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
        raise ProviderError("invalid_token", "the ID token's subject is not usable")
    return identities.Claims(meta.issuer, subject, claims.get("email"), claims.get("email_verified"), claims.get("name"))


# -- the two steps --

def settings(conn: sqlite3.Connection) -> Settings:
    """What a sign-in needs, or `Refused` (not configured) when OIDC is off or incomplete."""
    issuer = system_properties.get_value(conn, system_properties.OIDC_ISSUER)
    client_id = system_properties.get_value(conn, system_properties.OIDC_CLIENT_ID)
    try:
        public_url = config.public_url()
    except config.ConfigurationError:
        public_url = None
    if identities.current_fingerprint(conn) is None or issuer is None or client_id is None or public_url is None:
        raise identities.Refused(identities.NOT_CONFIGURED, "OIDC is off or not fully set up")
    return Settings(issuer, client_id, public_url)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def begin_login(conn: sqlite3.Connection, return_path: str, now: datetime | None = None) -> tuple[str, str]:
    """Make a login transaction and return (the address to send the browser to, the browser-binding value to put in a cookie).
    `return_path` must already be a safe local path."""
    now = now or clock.now()
    chosen = settings(conn)
    meta = metadata(chosen.issuer)
    state, nonce, verifier, binding = (secrets.token_urlsafe(n) for n in (32, 32, 48, 32))
    with db.write_transaction(conn):
        writer.sys_delete(conn, "sys_login_transactions", [("expires_at", "<=", _stamp(now))])
        if conn.execute("SELECT COUNT(*) FROM sys_login_transactions").fetchone()[0] >= MAX_PENDING:
            raise LoginError("busy", "too many sign-ins are in progress")
        writer.sys_insert(conn, "sys_login_transactions", {
            "state_hash": _hash(state), "binding_hash": _hash(binding), "nonce": nonce, "code_verifier": verifier,
            "return_path": return_path[:2000], "config_fingerprint": identities.current_fingerprint(conn),
            "created_at": _stamp(now), "expires_at": _stamp(now + TRANSACTION_LIFETIME)})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": chosen.client_id, "redirect_uri": chosen.redirect_uri, "scope": SCOPE,
        "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
    separator = "&" if urllib.parse.urlsplit(meta.authorization_endpoint).query else "?"
    return f"{meta.authorization_endpoint}{separator}{query}", binding


def abandon(conn: sqlite3.Connection, state: str | None) -> None:
    """Forget a login in progress, as when the provider sent the person back with an error."""
    if state and len(state) <= 200:
        writer.sys_delete(conn, "sys_login_transactions", [("state_hash", "=", _hash(state))])


def _consume(conn: sqlite3.Connection, state: str | None, now: datetime) -> sqlite3.Row | None:
    """The login transaction for this state, removed whether or not it is still good, so it cannot be used twice, not even
    by a request that then fails."""
    if not state or len(state) > 200:
        return None
    with db.write_transaction(conn):
        row = conn.execute("SELECT * FROM sys_login_transactions WHERE state_hash = ?", (_hash(state),)).fetchone()
        if row is not None:
            writer.sys_delete(conn, "sys_login_transactions", [("state_hash", "=", row["state_hash"])])
    return row if row is not None and row["expires_at"] > _stamp(now) else None


def finish_login(conn: sqlite3.Connection, binding: str | None, state: str | None, code: str | None,
                 now: datetime | None = None) -> LoginResult:
    """The browser has come back from the provider: check it is the browser that began this login, trade the code for an ID
    token, validate it and sign the person in. Raises `LoginError`, `ProviderError` or `identities.Refused`."""
    now = now or clock.now()
    row = _consume(conn, state, now)
    if row is None:
        raise LoginError("expired", "there is no login in progress for this state, or it ran out or was used")
    if not binding or not hmac.compare_digest(_hash(binding), row["binding_hash"]):
        raise LoginError("invalid", "the browser is not the one that began this login")
    if not code or len(code) > 2048:
        raise LoginError("invalid", "the provider sent no code")
    chosen = settings(conn)
    if identities.current_fingerprint(conn) != row["config_fingerprint"]:
        raise LoginError("expired", "the provider settings changed since this login began")
    secret = config.oidc_client_secret()
    if secret is None:
        raise identities.Refused(identities.NOT_CONFIGURED, "there is no client secret")
    meta = metadata(chosen.issuer)
    token = exchange_code(meta, chosen.client_id, secret, chosen.redirect_uri, code, row["code_verifier"])
    claims = validate_id_token(token, meta, chosen.client_id, row["nonce"], now.timestamp())
    return LoginResult(identities.sign_in(conn, claims, now), row["return_path"])

"""A fake OpenID Connect provider for the tests: a real HTTP server on 127.0.0.1 with its own signing keys, so Northstar's
own request code (no redirects, size limit, time limit, discovery, key fetch, code exchange) really runs. It is a thread in the
test process. Synthetic data only: every key, secret and token here is made up for the test."""

import base64
import functools
import hashlib
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey

CLIENT_ID = "northstar-test"
CLIENT_SECRET = "synthetic-client-secret-for-tests"
ACCESS_TOKEN = "access-token-that-must-never-be-stored"


@functools.cache
def rsa_key(kid: str) -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig"})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeProvider:
    """Serves discovery, a key set and a token endpoint. Tests change its fields to make it misbehave, and read `requests`
    to see exactly what Northstar sent."""

    def __init__(self):
        self.kid = "k1"
        self.extra_keys: list[str] = []           # kids of other keys to publish as well
        self.algorithms = ["RS256"]
        self.auth_methods: list[str] | None = ["client_secret_basic"]
        self.discovery_issuer: str | None = None  # a different issuer inside the discovery document
        self.endpoint_overrides: dict[str, str] = {}
        self.discovery_status = 200
        self.jwks_status = 200
        self.token_status = 200
        self.redirect_paths: dict[str, str] = {}  # a path that answers with a redirect to this address
        self.oversize_paths: set[str] = set()
        self.delay = 0.0
        self.published_kids: list[str] | None = None      # the kids in the key set, if not just the signing key
        self.codes: dict[str, dict] = {}
        self.requests: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self.issuer = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()

    # -- what a browser does at the provider --

    def authorize(self, location: str, claims: dict | None = None, **options) -> tuple[str, dict]:
        """Accept an authorization request (the address Northstar redirected the browser to) and return the code the browser
        would bring back, and the request's parameters. `claims` are changes to the ID token's claims. `options` change how
        the token is made: key, alg, kid, header, raw (a ready-made token), nonce (to sign a different one)."""
        parts = urllib.parse.urlsplit(location)
        assert f"{parts.scheme}://{parts.netloc}" == self.issuer and parts.path == "/authorize", location
        params = {key: values[0] for key, values in urllib.parse.parse_qs(parts.query).items()}
        assert params["response_type"] == "code" and params["code_challenge_method"] == "S256"
        code = "code-" + _b64(hashlib.sha256(f"{len(self.codes)}{time.time()}".encode()).digest())[:20]
        self.codes[code] = {"params": params, "claims": claims or {}, "options": options, "used": False}
        return code, params

    def id_token(self, params: dict, claims: dict, **options) -> str:
        now = int(time.time())
        payload = {"iss": self.issuer, "aud": CLIENT_ID, "sub": "subject-1", "exp": now + 300, "iat": now,
                   "nonce": options.get("nonce", params["nonce"]), "email": "alex@example.test", "email_verified": True,
                   "name": "Alex Example"}
        payload.update(claims)
        payload = {key: value for key, value in payload.items() if value is not None}      # None removes a claim
        if "raw" in options:
            return options["raw"]
        alg = options.get("alg", "RS256")
        if alg == "none":
            header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
            return f"{header}.{_b64(json.dumps(payload).encode())}."
        if alg.startswith("HS"):
            return jwt.encode({"alg": alg}, payload, OctKey.import_key("s" * 48), algorithms=[alg])
        kid = options.get("kid", self.kid)
        header = {"alg": alg, "kid": kid, **options.get("header", {})}
        return jwt.encode(header, payload, options.get("key", rsa_key(kid)), algorithms=[alg])

    # -- the server --

    def _handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body, content_type="application/json", extra=None):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def _record(self, body=b""):
                provider.requests.append({"path": self.path, "method": self.command, "headers": dict(self.headers.items()),
                                          "form": dict(urllib.parse.parse_qsl(body.decode()))})
                if provider.delay:
                    time.sleep(provider.delay)
                if self.path in provider.redirect_paths:
                    self._send(302, b"", extra={"Location": provider.redirect_paths[self.path]})
                    return True
                if self.path in provider.oversize_paths:
                    self._send(200, b"{" + b" " * 1_100_000 + b"}")
                    return True
                return False

            def do_GET(self):
                if self._record():
                    return
                if self.path == "/.well-known/openid-configuration":
                    if provider.discovery_status != 200:
                        return self._send(provider.discovery_status, {"error": "unavailable"})
                    document = {
                        "issuer": provider.discovery_issuer or provider.issuer,
                        "authorization_endpoint": f"{provider.issuer}/authorize", "token_endpoint": f"{provider.issuer}/token",
                        "jwks_uri": f"{provider.issuer}/jwks", "id_token_signing_alg_values_supported": provider.algorithms}
                    if provider.auth_methods is not None:
                        document["token_endpoint_auth_methods_supported"] = provider.auth_methods
                    document.update(provider.endpoint_overrides)
                    return self._send(200, document)
                if self.path == "/jwks":
                    if provider.jwks_status != 200:
                        return self._send(provider.jwks_status, {"error": "unavailable"})
                    kids = provider.published_kids or [provider.kid, *provider.extra_keys]
                    return self._send(200, {"keys": [rsa_key(kid).as_dict(private=False) for kid in kids]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self._record(body):
                    return
                if self.path != "/token":
                    return self._send(404, {"error": "not found"})
                if provider.token_status != 200:
                    return self._send(provider.token_status, {"error": "server_error"})
                form = dict(urllib.parse.parse_qsl(body.decode()))
                entry = provider.codes.get(form.get("code", ""))
                if entry is None or entry["used"]:
                    return self._send(400, {"error": "invalid_grant"})
                entry["used"] = True
                params = entry["params"]
                challenge = _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                if challenge != params["code_challenge"] or form.get("redirect_uri") != params["redirect_uri"]:
                    return self._send(400, {"error": "invalid_grant"})
                header = self.headers.get("Authorization", "")
                expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                in_body = form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET
                if (header != expected) and not in_body:
                    return self._send(401, {"error": "invalid_client"})
                token = provider.id_token(params, entry["claims"], **entry["options"])
                self._send(200, {"id_token": token, "access_token": ACCESS_TOKEN, "token_type": "Bearer"})

        return Handler

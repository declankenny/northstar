"""Where things live. One place, so the app and the backup tool always agree."""

import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DB_PATH = "data/northstar.db"


def database_path() -> Path:
    """The SQLite file: NORTHSTAR_DB if set, otherwise data/northstar.db."""
    return Path(os.environ.get("NORTHSTAR_DB", DEFAULT_DB_PATH))


class ConfigurationError(Exception):
    """A deployment setting that is ambiguous, unreadable or malformed. The message names the setting, never its value."""


def oidc_client_secret() -> str | None:
    """The OIDC client secret, from NORTHSTAR_OIDC_CLIENT_SECRET_FILE (a file holding it) or NORTHSTAR_OIDC_CLIENT_SECRET,
    or None when neither is set. Setting both is an error, because it is unclear which one is meant. It is a credential: it
    is never logged, shown, stored in a system property or put in an error message."""
    file = os.environ.get("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", "").strip()
    direct = os.environ.get("NORTHSTAR_OIDC_CLIENT_SECRET", "")
    if file and direct:
        raise ConfigurationError(
            "Both NORTHSTAR_OIDC_CLIENT_SECRET_FILE and NORTHSTAR_OIDC_CLIENT_SECRET are set. Set only one of them.")
    if file:
        try:
            secret = Path(file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raise ConfigurationError(f"NORTHSTAR_OIDC_CLIENT_SECRET_FILE ({file}) can't be read as text.") from None
        if not secret:
            raise ConfigurationError(f"NORTHSTAR_OIDC_CLIENT_SECRET_FILE ({file}) is empty.")
        return secret
    return direct.strip() or None


def public_url() -> str | None:
    """The address people use to reach Northstar, from NORTHSTAR_PUBLIC_URL, as scheme://host[:port] with no trailing slash,
    or None when it is not set. It builds the callback address registered with the OIDC provider, so it is never worked
    out from the Host or forwarded headers. It must be HTTPS. Plain HTTP is accepted only for localhost, 127.0.0.1 and
    [::1], for trying Northstar out on one machine."""
    raw = os.environ.get("NORTHSTAR_PUBLIC_URL", "").strip()
    if not raw:
        return None
    if not raw.isprintable() or " " in raw:       # the URL parser would silently drop a tab or line break
        raise ConfigurationError("NORTHSTAR_PUBLIC_URL must be an address such as https://northstar.example.com, with no path.")
    problem = ConfigurationError(
        "NORTHSTAR_PUBLIC_URL must be an address such as https://northstar.example.com, with no path. "
        "Plain http:// is accepted only for localhost.")
    try:
        parts = urlsplit(raw)
        host, _ = parts.hostname, parts.port
    except ValueError:
        raise problem from None
    local = host in ("localhost", "127.0.0.1", "::1")
    if (parts.scheme != "https" and not (parts.scheme == "http" and local)) or not host or parts.username is not None \
            or parts.password is not None or parts.path not in ("", "/") or "?" in raw or "#" in raw:
        raise problem
    return f"{parts.scheme}://{parts.netloc.lower()}"


def check_environment() -> None:
    """At startup: refuse to start on an OIDC deployment setting that is ambiguous or malformed, with a message that says
    which one. A secret that is simply not set is not an error here: OIDC cannot be turned on without it."""
    oidc_client_secret()
    public_url()


def cookie_secure() -> bool:
    """Whether the login cookie is marked Secure (sent over HTTPS only).

    Off by default because the app runs locally over plain HTTP. Set NORTHSTAR_COOKIE_SECURE=1
    when it is served over HTTPS.
    """
    return os.environ.get("NORTHSTAR_COOKIE_SECURE", "") == "1"

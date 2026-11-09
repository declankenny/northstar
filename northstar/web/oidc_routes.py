"""The two public routes of OIDC sign-in: the start and the return from the identity provider. See docs/design/oidc.

Both are plain GET requests that answer with a redirect, so the page never handles a token. Nothing else about OIDC is public.
A refusal or a failure sends the person back to the sign-in page with `?oidc_error=<code>`, a short fixed code and never the
provider's own words, a token or a claim, and the details go to the log, which never holds those either.

Abuse is limited with the sign-in throttle (northstar/throttle.py), counted under their own kind so that nothing a visitor types
as an email can be their key, and OIDC and password sign-in do not use up each other's allowance: starting a login counts until a login succeeds, and a return that is not a login
in progress or whose token is not valid counts until one succeeds. A provider that is down, or a person who is not allowed in,
does not count.
"""

from contextlib import closing

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from northstar import clock, config, db, identities, oidc, sessions, throttle
from northstar.web import auth_routes

router = APIRouter(prefix="/api/auth/oidc")
BINDING_COOKIE = "northstar_oidc"
BINDING_PATH = "/api/auth/oidc"
KIND = "oidc"                      # the throttle's namespace for these counts, which an email can never be in
START_KEY = "start"
RETURN_KEY = "return"
# What the sign-in page is told, by code. Each is fixed text written here.
CODES = ("not_allowed", "email_unverified", "not_configured", "expired", "provider_unavailable", "cancelled",
         "invalid_token", "busy", "throttled")


def _back(code: str) -> RedirectResponse:
    """To the sign-in page with the reason, and without the browser-binding cookie, which is of no more use."""
    response = RedirectResponse(f"/login?oidc_error={code}", status_code=303)
    response.delete_cookie(BINDING_COOKIE, path=BINDING_PATH)
    response.headers["Cache-Control"] = "no-store"
    return response


def _log(message: str, reason: str) -> None:
    throttle.log.warning("OIDC sign-in %s: %s.", message, reason)


@router.get("/login")
def start(request: Request, next: str = "/"):
    """Begin a sign-in: note it, set the browser-binding cookie and send the browser to the provider."""
    address = throttle.address_of(request)
    with closing(db.connect(request.app.state.db_path)) as conn:
        _, wait = throttle.begin(conn, START_KEY, address, clock.now(), KIND)
        if wait is not None:
            _log("throttled", f"too many sign-ins started from {address or 'an unknown address'}")
            return _back("throttled")
        try:
            url, binding = oidc.begin_login(conn, auth_routes.safe_next(next))
        except identities.Refused as refused:
            _log("not started", refused.reason)
            return _back(refused.code)
        except oidc.LoginError as failed:
            _log("not started", failed.reason)
            return _back(failed.code)
        except oidc.ProviderError as failed:
            _log("not started", failed.reason)
            return _back("provider_unavailable")
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(BINDING_COOKIE, binding, max_age=int(oidc.TRANSACTION_LIFETIME.total_seconds()), httponly=True,
                        samesite="lax", secure=config.cookie_secure(), path=BINDING_PATH)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
def finish(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    """The provider sends the browser back here. On success the person is signed in, any session this browser had is ended,
    and they go on to the page they asked for."""
    address = throttle.address_of(request)
    with closing(db.connect(request.app.state.db_path)) as conn:
        _, wait = throttle.begin(conn, RETURN_KEY, address, clock.now(), KIND)
        if wait is not None:
            _log("throttled", f"too many returns from {address or 'an unknown address'}")
            return _back("throttled")
        if error is not None:
            oidc.abandon(conn, state)
            throttle.clear(conn, RETURN_KEY, address, KIND)       # the person or the provider turned it down: not an attack
            _log("turned down by the provider", error if error.isidentifier() and len(error) <= 40 else "an error code")
            return _back("cancelled" if error == "access_denied" else "provider_unavailable")
        try:
            result = oidc.finish_login(conn, request.cookies.get(BINDING_COOKIE), state, code)
        except oidc.LoginError as failed:
            _log("refused", failed.reason)              # not a login in progress for this browser: counts against the address
            return _back("busy" if failed.code == "busy" else "expired")
        except oidc.ProviderError as failed:
            _log("failed", failed.reason)
            if failed.code != "invalid_token":
                throttle.clear(conn, RETURN_KEY, address, KIND)       # the provider is down or misbehaving: not the visitor's doing
            return _back("invalid_token" if failed.code == "invalid_token" else "provider_unavailable")
        except identities.Refused as refused:
            _log("refused", refused.reason)
            throttle.clear(conn, RETURN_KEY, address, KIND)       # a real login by someone who may not come in
            return _back(refused.code)
        sessions.end_session(conn, request.cookies.get(auth_routes.COOKIE))     # this browser gets the new session only
        throttle.clear(conn, RETURN_KEY, address, KIND)
        throttle.clear(conn, START_KEY, address, KIND)
    response = RedirectResponse(auth_routes.safe_next(result.return_path), status_code=303)
    response.set_cookie(auth_routes.COOKIE, result.signed_in.token, max_age=result.signed_in.max_age, httponly=True,
                        samesite="lax", secure=config.cookie_secure())
    response.delete_cookie(BINDING_COOKIE, path=BINDING_PATH)
    response.headers["Cache-Control"] = "no-store"
    return response

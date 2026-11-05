"""Sign in and sign out, as JSON for the React sign-in screen. The sign-in page itself is a page of the React app (see
app.py). Every other route is protected by the middleware in app.py."""

from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from northstar import clock, config, db, locales, sessions, throttle, users
from northstar.writer import Operation

router = APIRouter(prefix="/api/auth")
pages = APIRouter()
COOKIE = "northstar_session"
LANDING = "/dashboard"   # where people go after signing in, and from the site root


def current_user(request: Request):
    """The signed-in user (id, email, display_name, is_admin). The one place routes ask who this is.

    The middleware has already refused anyone who is not signed in, so this is never None
    inside a protected route.
    """
    return request.state.user


def run(request: Request, action):
    """Run `action(conn)` on a connection that is closed afterwards. A broken rule it raises becomes an error response
    (see northstar.web.errors), so callers do not catch it."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        user = getattr(request.state, "user", None)
        # Every message the rules write for this person says its dates and numbers in their own format.
        with locales.speak_as(locales.for_user(conn, user["id"]) if user else None):
            return action(conn)


def operation(request: Request, conn, kind: str = "ui_edit", detail: dict | None = None) -> Operation:
    """The signed-in user's action on this connection: what every write is made through (see northstar.writer)."""
    return Operation(conn, current_user(request)["id"], kind, detail)


def require_admin(request: Request):
    """A route dependency: only admins get through. Signed-out users never reach it (see app.py)."""
    user = current_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can do that.")
    return user


def safe_next(target: str) -> str:
    """Only send people back to a path on this site, never to another address.

    The site root and anything unsafe go to the landing page: the Dashboard. Unsafe includes any control
    character or space: browsers drop tabs and newlines from an address, so "/<tab>/evil.com" would mean
    "//evil.com". The response library happens to percent-encode those, but this check does not rely on that.
    """
    if (target != "/" and target.startswith("/") and not target.startswith("//") and "\\" not in target
            and target.isprintable() and not any(char.isspace() for char in target)):
        parts = urlsplit(target)
        if not parts.scheme and not parts.netloc:
            return target
    return LANDING


@pages.get("/login", include_in_schema=False)
def sign_in_page(request: Request, next: str = "/"):
    """The sign-in page is a page of the React app like any other. Someone already signed in is sent on."""
    if request.state.user:
        return RedirectResponse(safe_next(next), status_code=303)
    index = request.app.state.spa_index
    if not index.is_file():
        raise HTTPException(status_code=404)       # no build: there is no page to show
    return FileResponse(index)


class SignIn(BaseModel):
    email: str = ""
    password: str = ""
    next: str = "/"


@router.post("/login")
def login(body: SignIn, request: Request):
    """Sign in. The answer says where to go next, already checked by safe_next, and the screen goes there with a full
    page load. A refusal is a `detail` the screen shows as it is."""
    next_path = safe_next(body.next)
    address = throttle.address_of(request)
    with closing(db.connect(request.app.state.db_path)) as conn:
        # The attempt takes its slot first and is only cleared by a success, so many requests at once
        # cannot all be checked before the first failure is recorded. A blocked attempt does not check
        # the password at all, so a correct guess cannot get through during a block.
        _, wait = throttle.begin(conn, body.email, address, clock.now())
        if wait is not None:
            throttle.log.warning("Sign-in throttled for %s: try again in %s.", address or "an unknown address", throttle.describe(wait))
            return JSONResponse({"detail": f"Too many sign-in attempts. Try again in about {throttle.describe(wait)}."},
                                status_code=429, headers={"Retry-After": str(wait)})
        user = users.authenticate(conn, body.email, body.password)
        if user is None:
            return JSONResponse({"detail": "That email and password don't match."}, status_code=400)
        throttle.clear(conn, body.email, address)
        token = sessions.create_session(conn, user["id"])
    response = JSONResponse({"next": next_path})
    response.set_cookie(COOKIE, token, max_age=sessions.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=config.cookie_secure())
    return response


@router.post("/logout")
def logout(request: Request):
    with closing(db.connect(request.app.state.db_path)) as conn:
        sessions.end_session(conn, request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE)
    return response

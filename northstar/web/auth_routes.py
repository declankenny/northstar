"""Login and logout. Every other route is protected by the middleware in app.py."""

from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from northstar import clock, config, db, sessions, throttle, users
from northstar.writer import Operation

router = APIRouter()
COOKIE = "northstar_session"
LANDING = "/dashboard"   # where people go after signing in, and from the site root


def current_user(request: Request):
    """The signed-in user (id, email, display_name, is_admin). The one place routes ask who this is.

    The middleware has already refused anyone who is not signed in, so this is never None
    inside a protected route.
    """
    return request.state.user


def operation(request: Request, conn) -> Operation:
    """The signed-in user's action on this connection: what every write is made through (see northstar.writer)."""
    return Operation(conn, current_user(request)["id"])


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


def _page(request: Request, status: int, next_path: str, error: str | None = None, email: str = ""):
    context = {"error": error, "next": next_path, "email": email}
    return request.app.state.templates.TemplateResponse(request, "login.html", context, status_code=status)


@router.get("/login")
def login_form(request: Request, next: str = "/"):
    if request.state.user:
        return RedirectResponse(safe_next(next), status_code=303)
    return _page(request, 200, safe_next(next))


@router.post("/login")
def login(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("/")):
    next_path = safe_next(next)
    address = throttle.address_of(request)
    with closing(db.connect(request.app.state.db_path)) as conn:
        # The attempt takes its slot first and is only cleared by a success, so many requests at once
        # cannot all be checked before the first failure is recorded. A blocked attempt does not check
        # the password at all, so a correct guess cannot get through during a block.
        _, wait = throttle.begin(conn, email, address, clock.now())
        if wait is not None:
            throttle.log.warning("Sign-in throttled for %s: try again in %s.", address or "an unknown address", throttle.describe(wait))
            response = _page(request, 429, next_path,
                             f"Too many sign-in attempts. Try again in about {throttle.describe(wait)}.", email)
            response.headers["Retry-After"] = str(wait)
            return response
        user = users.authenticate(conn, email, password)
        if user is None:
            return _page(request, 400, next_path, "That email and password don't match.", email)
        throttle.clear(conn, email, address)
        token = sessions.create_session(conn, user["id"])
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(COOKIE, token, max_age=sessions.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=config.cookie_secure())
    return response


@router.post("/logout")
def logout(request: Request):
    with closing(db.connect(request.app.state.db_path)) as conn:
        sessions.end_session(conn, request.cookies.get(COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response

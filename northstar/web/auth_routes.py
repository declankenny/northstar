"""Login and logout. Every other route is protected by the middleware in app.py."""

from contextlib import closing

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from northstar import config, db, sessions, users

router = APIRouter()
COOKIE = "northstar_session"


def current_user(request: Request):
    """The signed-in user (id, email, display_name, is_admin). The one place routes ask who this is.

    The middleware has already refused anyone who is not signed in, so this is never None
    inside a protected route.
    """
    return request.state.user


def require_admin(request: Request):
    """A route dependency: only admins get through. Signed-out users never reach it (see app.py)."""
    user = current_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can do that.")
    return user


def safe_next(target: str) -> str:
    """Only send people back to a path on this site, never to another address."""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


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
    with closing(db.connect(request.app.state.db_path)) as conn:
        user = users.authenticate(conn, email, password)
        if user is None:
            return _page(request, 400, next_path, "That email and password don't match.", email)
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

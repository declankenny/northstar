"""The first-run setup page and its JSON endpoints. These are public (see app.py): nobody is signed in yet. What protects them
is the rule in setup.py that they work only while no administrator exists, and a setup session that needs the token from the
container log. Like the other routes they call plain functions and add no rules of their own.

The page is a page of the React app, served only while setup is open and otherwise sent to the sign-in page.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from northstar import config, setup, throttle
from northstar.web.auth_routes import run

router = APIRouter(prefix="/api/setup")
pages = APIRouter()
COOKIE = "northstar_setup"        # the setup session; never a signed-in session, and sent only to /api/setup
COOKIE_PATH = "/api/setup"


def _gate(request: Request) -> setup.SetupGate:
    return request.app.state.setup


@pages.get("/setup", include_in_schema=False)
def setup_page(request: Request):
    """The setup page while setup is open. Once an administrator exists there is nothing to show, so go to sign-in."""
    if not run(request, setup.is_open):
        return RedirectResponse("/login", status_code=303)
    index = request.app.state.spa_index
    if not index.is_file():
        raise HTTPException(status_code=404)       # no build: there is no page to show
    return FileResponse(index)


@router.get("/status")
def status(request: Request):
    """Which screen to show: `complete` (an administrator exists), `token` (enter the setup token) or `form`. Says nothing
    else, so it exposes no household data."""
    def action(conn):
        if not setup.is_open(conn):
            return {"state": "complete"}
        return {"state": "form" if _gate(request).authorized(request.cookies.get(COOKIE)) else "token"}
    return run(request, action)


class Token(BaseModel):
    token: str = ""


@router.post("/token")
def enter_token(body: Token, request: Request):
    """Give the setup token and get a setup session for this browser. It does not create anything or use the token up. A wrong
    token is a generic refusal, and too many from one address are refused for a while."""
    def action(conn):
        if not setup.is_open(conn):
            raise setup.SetupClosed("Setup has already been completed.")
        gate = _gate(request)
        try:
            accepted = gate.check_token(body.token.strip(), throttle.address_of(request))
        except setup.TooManyAttempts as wait:
            return JSONResponse({"detail": f"Too many wrong tokens. Try again in about {throttle.describe(wait.wait)}."},
                                status_code=429, headers={"Retry-After": str(wait.wait)})
        if not accepted:
            return JSONResponse({"detail": "That isn't the setup token. Copy it from the container log."}, status_code=400)
        response = Response(status_code=204)
        response.set_cookie(COOKIE, gate.grant(), max_age=setup.SESSION_SECONDS, httponly=True, samesite="strict",
                            secure=config.cookie_secure(), path=COOKIE_PATH)
        return response
    return run(request, action)


@router.get("/options")
def options(request: Request):
    """What the form offers and where each choice starts. Needs a setup session."""
    def action(conn):
        setup.require_session(conn, _gate(request), request.cookies.get(COOKIE))
        return setup.options(conn)
    return run(request, action)


class Setup(BaseModel):
    email: str = ""
    display_name: str = ""
    password: str = ""
    currency: str | None = None
    locale: str = ""
    timezone: str = ""


@router.post("")
def finish(body: Setup, request: Request):
    """Create the administrator and save the initial properties together, or save nothing. The answer is the email, to prefill
    the sign-in page. Nobody is signed in by it."""
    def action(conn):
        email = setup.complete(conn, _gate(request), request.cookies.get(COOKIE), setup.Submission(
            email=body.email, display_name=body.display_name, password=body.password, currency=body.currency,
            locale=body.locale, timezone=body.timezone))
        response = JSONResponse({"email": email})
        response.delete_cookie(COOKIE, path=COOKIE_PATH)
        return response
    return run(request, action)

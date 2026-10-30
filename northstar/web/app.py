"""App setup. Page routes live in their own modules and call plain functions."""

from contextlib import closing
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from northstar import config, db, sessions
from northstar.money import cents_to_input, format_cents
from northstar.web import accounts_routes, api_routes, auth_routes, balances_routes, dashboard_routes, types_routes

WEB_DIR = Path(__file__).parent
SPA_DIR = WEB_DIR / "spa"        # the built React app (see frontend/); absent until it is built
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


async def refuse_cross_site_posts(request: Request, call_next):
    """With no login, refuse changes sent from another website's page.

    Browsers attach an Origin header to form posts. If it names a different site than
    the one being asked, the post came from somewhere else and is refused. Requests with
    no Origin header, such as curl or the test client, are allowed.
    """
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Cross-site request refused.", status_code=403)
    return await call_next(request)


async def require_login(request: Request, call_next):
    """Every page and endpoint needs a signed-in user, except the login page and its stylesheet.

    Pages redirect to the login page. The JSON API answers 401. The signed-in user is left on
    request.state.user for auth_routes.current_user().
    """
    with closing(db.connect(request.app.state.db_path)) as conn:
        request.state.user = sessions.user_for_token(conn, request.cookies.get(auth_routes.COOKIE))
    path = request.url.path
    if request.state.user or path == "/login" or path.startswith("/static/"):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Not signed in."}, status_code=401)
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


def create_app(db_path: str | Path | None = None) -> FastAPI:
    db_path = Path(db_path) if db_path else config.database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(db_path)) as conn:
        db.migrate(conn)

    app = FastAPI(title="Northstar")
    app.state.db_path = db_path
    app.state.templates = Jinja2Templates(directory=WEB_DIR / "templates")
    app.state.templates.env.filters["money"] = format_cents
    app.state.templates.env.filters["money_input"] = cents_to_input
    app.middleware("http")(refuse_cross_site_posts)
    app.middleware("http")(require_login)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(auth_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(balances_routes.router)
    app.include_router(accounts_routes.router)
    app.include_router(types_routes.router)
    app.include_router(api_routes.router)
    if (SPA_DIR / "index.html").exists():
        app.mount("/app", StaticFiles(directory=SPA_DIR, html=True), name="spa")

    return app

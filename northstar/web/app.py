"""App setup. Page routes live in their own modules and call plain functions."""

import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from northstar import db
from northstar.money import cents_to_input, format_cents
from northstar.web import accounts_routes, balances_routes, types_routes

WEB_DIR = Path(__file__).parent
DEFAULT_DB_PATH = "data/northstar.db"
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


def create_app(db_path: str | Path | None = None) -> FastAPI:
    db_path = Path(db_path or os.environ.get("NORTHSTAR_DB", DEFAULT_DB_PATH))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(db_path)) as conn:
        db.migrate(conn)

    app = FastAPI(title="Northstar")
    app.state.db_path = db_path
    app.state.templates = Jinja2Templates(directory=WEB_DIR / "templates")
    app.state.templates.env.filters["money"] = format_cents
    app.state.templates.env.filters["money_input"] = cents_to_input
    app.middleware("http")(refuse_cross_site_posts)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(balances_routes.router)
    app.include_router(accounts_routes.router)
    app.include_router(types_routes.router)

    @app.get("/")
    def home():
        # Temporary: the Dashboard replaces this when it exists.
        return RedirectResponse("/accounts", status_code=307)

    return app

"""Page routes. They call plain functions and hand the results to templates."""

import os
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from northstar import account_types, clock, db

WEB_DIR = Path(__file__).parent
DEFAULT_DB_PATH = "data/northstar.db"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    db_path = Path(db_path or os.environ.get("NORTHSTAR_DB", DEFAULT_DB_PATH))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(db_path)) as conn:
        db.migrate(conn)

    app = FastAPI(title="Northstar")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with closing(db.connect(db_path)) as conn:
            types = account_types.list_types(conn)
        return templates.TemplateResponse(
            request, "index.html", {"today": clock.today(), "types": types}
        )

    return app

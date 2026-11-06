"""App setup. Routes live in their own modules and call plain functions."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from northstar import config, db, scheduler, sessions, system_properties, throttle, users
from northstar.web import (account_api, api_routes, auth_routes, currencies_api, errors, import_api, imports_api, profile_api, security_headers,
                           system_properties_api, types_api, update_api, users_api, version_api)

WEB_DIR = Path(__file__).parent
SPA_DIR = WEB_DIR / "spa"        # the built React app (see frontend/); absent until it is built
# First parts of an address that belong to the server. The React app owns every other address.
SERVER_PATHS = ("api", "login", "static")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# What a signed-out visitor may fetch: the sign-in page, its endpoint, and the files the page is made of.
PUBLIC_PATHS = ("/login", "/api/auth/login")
PUBLIC_PREFIXES = ("/static/", "/assets/")


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
    """Every page and endpoint needs a signed-in user, except the sign-in page and its endpoint, the files of the
    build (/assets) and the public files (/static).

    Pages redirect to the sign-in page. The JSON API answers 401. The signed-in user is left on
    request.state.user for auth_routes.current_user().
    """
    with closing(db.connect(request.app.state.db_path)) as conn:
        request.state.user = sessions.user_for_token(conn, request.cookies.get(auth_routes.COOKIE))
    path = request.url.path
    if request.state.user or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Not signed in."}, status_code=401)
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


def warn_if_cookie_is_not_secure() -> None:
    """Say so at startup when the sign-in cookie is not marked Secure, because that is easy to leave off."""
    if not config.cookie_secure():
        logging.getLogger("uvicorn.error").warning(
            "NORTHSTAR_COOKIE_SECURE is not set, so the sign-in cookie is also sent over plain HTTP, where anyone "
            "on the network can read it. That is fine for trying Northstar out on one machine. Anything beyond "
            "that should be served over HTTPS, with NORTHSTAR_COOKIE_SECURE=1 set (the value must be exactly 1).")


def create_app(db_path: str | Path | None = None) -> FastAPI:
    db_path = Path(db_path) if db_path else config.database_path()
    db.upgrade(db_path)     # a backup first if a migration is pending, and a refusal if the database is newer
    with closing(db.connect(db_path)) as conn:
        system_properties.apply_timezone(conn)      # what "today" is: the system.timezone setting, from TZ the first time
    throttle.log_limits()
    warn_if_cookie_is_not_secure()
    users.prepare_dummy_hash()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """The in-app scheduler runs for as long as the server does. The test client starts it only when it is used as a
        context manager, so a test that does not ask for it never has a background thread."""
        app.state.scheduler = scheduler.Scheduler(db_path)
        app.state.scheduler.start()
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.scheduler.stop)

    app = FastAPI(title="Northstar", lifespan=lifespan)
    app.state.db_path = db_path
    app.middleware("http")(refuse_cross_site_posts)
    app.middleware("http")(require_login)
    errors.install(app)
    security_headers.install(app)   # last, so it is outermost and covers the other middleware's responses
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.state.spa_index = SPA_DIR / "index.html"      # the sign-in page is that page (see auth_routes.sign_in_page)
    app.include_router(auth_routes.pages)
    app.include_router(auth_routes.router)
    app.include_router(types_api.router)
    app.include_router(system_properties_api.router)
    app.include_router(currencies_api.router)
    app.include_router(api_routes.router)
    app.include_router(account_api.router)
    app.include_router(update_api.router)
    app.include_router(import_api.router)
    app.include_router(imports_api.router)
    app.include_router(profile_api.router)
    app.include_router(users_api.router)
    app.include_router(version_api.router)

    @app.get("/", include_in_schema=False)
    def site_root():
        return RedirectResponse(auth_routes.LANDING, status_code=303)

    if (SPA_DIR / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def react_app(path: str):
            """The React app for any page address (/accounts/12, /balance-update), which then shows the
            right page itself. A real file of the build (under /assets) is served as that file. Anything
            that is not a page is a 404, never the app's HTML: a mistyped /api address or a missing
            script would otherwise come back as a web page."""
            first = path.split("/", 1)[0]
            if first in SERVER_PATHS or "\x00" in path:     # no file has a null byte in its name, and the file system calls raise on one
                raise HTTPException(status_code=404)
            # The requested path is only turned into a file after it is known to be inside the build, and the
            # file system is not asked about anything outside it.
            root = os.path.realpath(SPA_DIR)
            target = os.path.realpath(os.path.join(root, path))
            if path and target.startswith(root + os.sep) and os.path.isfile(target):
                return FileResponse(target)
            if first == "assets":
                raise HTTPException(status_code=404)
            return FileResponse(os.path.join(root, "index.html"))

    return app

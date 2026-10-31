# northstar

Self-hosted tracker of household net worth over time. `docs/spec.md` is the source of truth for scope.

## Sign in

Every page needs a login, and there is no default user. Create the first admin once, and the command asks for the password:

```
python -m northstar.users create you@example.com "Your Name" --admin
docker compose exec northstar python -m northstar.users create you@example.com "Your Name" --admin   # in Docker
```

`set-password EMAIL` changes a password and signs that user out everywhere, and `list` shows users. When the app is served over HTTPS, set `NORTHSTAR_COOKIE_SECURE=1`.

## Run it

Docker (how it normally runs): `docker compose up -d --build`, then open http://127.0.0.1:8000. The image builds the React frontend itself, so nothing else is needed.

Without Docker, for development (Python 3.14, Node):

```
pip install -e ".[dev]"
python -m pytest                      # Python tests
cd frontend && npm ci
npm test                              # frontend tests
npm run build                         # builds into northstar/web/spa, served at /app/
```

The app is at `/app/` (the site root `/` redirects there), and it needs the build above. The sign-in page at `/login` is the one server-rendered page.

To work on the frontend with live reload, run the Python app on port 8000
(`uvicorn --factory northstar.web.app:create_app`), then `npm run dev` in `frontend/` and open
http://127.0.0.1:5173/app/. The dev server sends `/api` and the sign-in page to the Python app.

Use synthetic data only when developing. Never point a development copy at a real database file.

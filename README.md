# northstar

[![CI](https://github.com/declankenny/northstar/actions/workflows/ci.yml/badge.svg)](https://github.com/declankenny/northstar/actions/workflows/ci.yml)

Self-hosted tracker of household net worth over time. `docs/spec.md` is the source of truth for scope.

> **Pre-release.** Northstar has no published release or Docker image yet. Run it from a checkout and with synthetic data only, and do not expose it to the internet: security headers and the other release hardening in `docs/spec.md` ("Release and distribution") are not built yet. All data in the tests and examples is synthetic.

Licensed under the [MIT License](LICENSE).

## Sign in

Every page needs a login, and there is no default user. Create the first admin once, and the command asks for the password:

```
python -m northstar.users create you@example.com "Your Name" --admin
docker compose exec northstar python -m northstar.users create you@example.com "Your Name" --admin   # in Docker
```

`set-password EMAIL` changes a password and signs that user out everywhere, and `list` shows users. When the app is served over HTTPS, set `NORTHSTAR_COOKIE_SECURE=1`.

### Limits on failed sign-ins

Failed sign-ins are limited: 5 in 15 minutes per email from one address, 30 an hour per email from any address, and 20 in 15 minutes per address. A blocked sign-in says how long to wait and does not check the password.

Behind a reverse proxy (Traefik, Caddy, nginx), tell the app which proxy to trust, or the app cannot see the visitors' real addresses and switches the per-address limit off (it logs a warning that says so). Set `FORWARDED_ALLOW_IPS` to the proxy's address or network, for example the Docker network the proxy shares with Northstar, and never to `*`. Without a proxy, set nothing.

```
FORWARDED_ALLOW_IPS=172.18.0.0/16
```

## Run it

Docker (how it normally runs): `docker compose up -d --build`, then open http://127.0.0.1:8000. The image builds the React frontend itself, so nothing else is needed.

Without Docker, for development (Python 3.14, Node):

```
pip install -e ".[dev]"
python -m pytest                      # Python tests
cd frontend && npm ci
npm test                              # frontend tests
npm run build                         # builds into northstar/web/spa, served from the site root
```

The app is at `/dashboard` and the pages around it (the site root `/` redirects there), and it needs the build above. The sign-in page at `/login` is the one server-rendered page.

To work on the frontend with live reload, run the Python app on port 8000
(`uvicorn --factory northstar.web.app:create_app`), then `npm run dev` in `frontend/` and open
http://127.0.0.1:5173/. The dev server sends `/api` and the sign-in page to the Python app.

Use synthetic data only when developing. Never point a development copy at a real database file.

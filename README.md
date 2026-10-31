# northstar

[![CI](https://github.com/declankenny/northstar/actions/workflows/ci.yml/badge.svg)](https://github.com/declankenny/northstar/actions/workflows/ci.yml)

Self-hosted tracker of household net worth over time. `docs/spec.md` is the source of truth for scope.

> **Pre-release.** Northstar has no published release or Docker image yet. Run it from a checkout and with synthetic data only, and do not expose it to the internet: the remaining release hardening in `docs/spec.md` ("Release and distribution") is not built yet. All data in the tests and examples is synthetic.

Licensed under the [MIT License](LICENSE). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Sign in

Every page needs a login, and there is no default user. Create the first admin once, and the command asks for the password:

```
python -m northstar.users create you@example.com "Your Name" --admin
docker compose exec northstar python -m northstar.users create you@example.com "Your Name" --admin   # in Docker
```

`set-password EMAIL` changes a password and signs that user out everywhere, and `list` shows users. When the app is served over HTTPS, set `NORTHSTAR_COOKIE_SECURE=1` (exactly `1`). Without it the app logs a warning at startup, because the sign-in cookie is then also sent over plain HTTP.

Passwords are hashed with scrypt, which is deliberately slow and memory-hungry: each sign-in takes about half a second and 128 MiB on a modern computer (more time on a small device such as a Raspberry Pi), and at most two run at the same time.

### Limits on failed sign-ins

Failed sign-ins are limited: 5 in 15 minutes per email from one address, 30 an hour per email from any address, and 20 in 15 minutes per address. A blocked sign-in says how long to wait and does not check the password.

Behind a reverse proxy (Traefik, Caddy, nginx), tell the app which proxy to trust, or the app cannot see the visitors' real addresses and switches the per-address limit off (it logs a warning that says so). Set `FORWARDED_ALLOW_IPS` to the proxy's address or network, for example the Docker network the proxy shares with Northstar, and never to `*`. Without a proxy, set nothing.

```
FORWARDED_ALLOW_IPS=172.18.0.0/16
```

## Run it

Docker (how it normally runs): `compose.yaml` uses the published image, and there is none yet, so until the first release build from source with `docker compose -f compose.dev.yaml up -d --build`, then open http://localhost:8000. The image builds the React frontend itself, so nothing else is needed. Settings go in a `.env` file beside the compose file (copy `.env.example`): `TZ`, `NORTHSTAR_PORT` and `NORTHSTAR_COOKIE_SECURE`. The cookie setting defaults to `1`, which browsers accept on `http://localhost` but drop on a plain-HTTP address such as `http://192.168.1.10:8000`, where sign-in then appears to do nothing: serve the app over HTTPS, or set it to `0` for a trial on your own network.

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

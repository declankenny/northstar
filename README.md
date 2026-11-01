# northstar

[![CI](https://github.com/declankenny/northstar/actions/workflows/ci.yml/badge.svg)](https://github.com/declankenny/northstar/actions/workflows/ci.yml)

Self-hosted tracker of household net worth over time. You enter the balance of each account by hand, and Northstar shows net worth and each account's history. It is one container and one SQLite file, with no bank feeds and no transactions. `docs/spec.md` is the source of truth for scope.

Northstar is version 0.x, so anything may change between minor versions, and the [changelog](CHANGELOG.md) says what. To run it for your household, [docs/operating.md](docs/operating.md) is the guide to installing the published image, putting it behind HTTPS, and upgrading and backing it up. Everything below is for trying it out and for development, with synthetic data. All data in the tests and examples is synthetic.

Licensed under the [MIT License](LICENSE). To report a vulnerability, see [SECURITY.md](SECURITY.md). To contribute, see [CONTRIBUTING.md](CONTRIBUTING.md), and for what changed in each version, [CHANGELOG.md](CHANGELOG.md).

## Try it in Docker

Docker builds the React frontend itself, so nothing else is needed. From a checkout:

```
cp .env.example .env
docker compose -f compose.dev.yaml up -d --build
docker compose -f compose.dev.yaml ps
```

When `ps` shows `healthy`, create the first admin. There is no default user. This runs inside the container, and the command asks for the password twice (at least 12 characters):

```
docker compose -f compose.dev.yaml exec northstar python -m northstar.users create you@example.com "Your Name" --admin
```

Then open <http://localhost:8000> and sign in. The app listens on `127.0.0.1` only. Settings go in `.env`: `TZ`, `NORTHSTAR_PORT` and `NORTHSTAR_COOKIE_SECURE`, which [docs/operating.md](docs/operating.md) explains, together with why a sign-in on a plain-HTTP address such as `http://192.168.1.10:8000` appears to do nothing.

## Run it from source, for development

You need Python 3.14 and Node. These commands run on the host and not in a container.

```
pip install -e ".[dev]"
cd frontend && npm ci && npm run build && cd ..
uvicorn --factory northstar.web.app:create_app
```

The build goes into `northstar/web/spa`, and the app serves it from the site root. The first start creates `data/northstar.db`, with its folder. With the app running, open a second terminal and create the first admin, which asks for the password. The command refuses to run before the app has set up the database:

```
python -m northstar.users create you@example.com "Your Name" --admin
```

Open <http://localhost:8000>, which redirects to `/dashboard`. The sign-in page at `/login` is the one page the server renders.

To work on the frontend with live reload, keep the Python app running on port 8000, then run `npm run dev` in `frontend/` and open <http://127.0.0.1:5173/>. The dev server sends `/api` and the sign-in page to the Python app.

Run the tests:

```
python -m pytest        # Python
cd frontend && npm test # frontend
```

Use synthetic data only, and never point a development copy at a real database file.

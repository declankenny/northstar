# Security policy

Northstar holds a household's financial position, so security reports are taken seriously. It is maintained by one person, in spare time, and this page says honestly what that means.

## Supported versions

Northstar is pre-1.0. Until 1.0, **only the latest minor version** (once 0.2 exists, that means 0.2.x and not 0.1.x) gets security fixes. A fix lands on `main` first and is then backported to the `release/X.Y` branch and published as a new patch release. If you run an older minor version, the fix is to update.

There is no published release yet. Until v0.1.0, run Northstar only with synthetic data and do not expose it to the internet.

## Reporting a vulnerability

**Please do not open a public issue or pull request for a vulnerability.**

Report it privately through GitHub: open the [Security tab](https://github.com/declankenny/northstar/security) and choose **Report a vulnerability**, or go straight to [the report form](https://github.com/declankenny/northstar/security/advisories/new). Only the maintainer can see it.

A useful report says what you found, the steps or a small proof of concept to reproduce it, the version or commit, and what an attacker gains. Use synthetic data, and never include real balances, credentials or a real database file.

## What to expect

- **Acknowledgement** within about 5 days. This is a best effort, not a guarantee: one person reads these.
- **Assessment**: I will say whether I can reproduce it and whether I think it is a vulnerability. If we disagree, I will explain why.
- **A fix**: there is no fixed deadline. I aim to fix serious problems (anything that exposes data, or lets someone sign in or act as another user) as quickly as I can, and to tell you when a release is planned.
- **Disclosure**: once a patched release exists, I publish a GitHub security advisory describing the problem and the fixed versions. Please keep the details private until then. If a report goes quiet for 90 days, you may disclose it, after telling me.
- **Credit**: you are named in the advisory if you want to be, and not if you don't.

There is no bug bounty.

## What counts as a vulnerability

Northstar is built for **one household that trusts its own members**. Within that model, these are vulnerabilities:

- Reading or changing data without being signed in.
- Signing in without the password, getting around the limit on failed sign-ins, or finding out which emails have accounts.
- An ordinary user doing something only an admin can (managing users or account types).
- Reaching another site's or another origin's data through the app, such as cross-site request forgery, cross-site scripting or a bypass of the content security policy.
- Reading files, other users' sessions or password hashes through the app.
- Anything in the published Docker image or its dependencies that gives an attacker code execution or data access.

These are **by design** and are not vulnerabilities:

- **Every signed-in user sees all household data.** There is no per-user data. Admins add and remove users, so only create accounts for people you trust with all of it.
- **There is no multi-factor authentication and no single sign-on yet.** If you need them, put Northstar behind a proxy that provides them (an SSO-aware reverse proxy) or keep it on a private network or VPN. OIDC sign-in is on the roadmap.
- **The app serves plain HTTP.** HTTPS is the operator's job, through a reverse proxy.
- **Someone with access to the server, the container or the database file** can read everything in it. A backup holds real data, password hashes and sessions: keep it somewhere private.

## What Northstar does for you

The details and the reasons are in [`docs/spec.md`](docs/spec.md) ("Security") and [`docs/decisions.md`](docs/decisions.md). In short:

- Every page and every API endpoint needs a signed-in user. There is no default user or password.
- Passwords are hashed with scrypt (128 MiB and about half a second per hash), and stored hashes are upgraded when the cost is raised.
- Failed sign-ins and wrong guesses of the current password are limited per email and per address.
- Sessions are random tokens in an `HttpOnly`, `SameSite=Lax` cookie. Only a hash of the token is stored, and they last 30 days.
- A strict content security policy, with no inline script or style, and changes made from another site are refused.
- Dependencies, base images and CI actions are pinned. Dependabot proposes every update, and CI fails on a known vulnerability in the Python and frontend dependencies and in the built image.

## Hardening notes for operators

- **Serve it over HTTPS** with a reverse proxy (Traefik, Caddy, nginx) and set `NORTHSTAR_COOKIE_SECURE=1`, exactly `1`. Without it the sign-in cookie is also sent over plain HTTP, and the app logs a warning at startup.
- **Tell the app which proxy to trust** with `FORWARDED_ALLOW_IPS` set to the proxy's address or network, never `*`. Otherwise the app cannot see visitors' real addresses and turns the per-address limit off (it logs a warning).
- **Add HSTS at the proxy.** Northstar leaves it to the proxy because only the proxy knows the domain is HTTPS for good.
- **Do not publish the app's port.** Let only the proxy reach it.
- **Use long, unique passwords.** The minimum is 12 characters. A password manager is the easy way.
- **Keep it up to date.** Fixes arrive as patch releases. Once the published image exists, updating is `docker compose pull && docker compose up -d`.
- **Back up the database** with `python -m northstar.backup create FILE`, and keep backups private.
- **If every admin is locked out**, the command line is the way back in: `python -m northstar.users set-password EMAIL`.

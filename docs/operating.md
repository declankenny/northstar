# Running Northstar

This is for someone running Northstar for their own household. You need a Linux machine (Intel or ARM, a Raspberry Pi is fine) with Docker and Docker Compose, and for use beyond that one machine, a reverse proxy that provides HTTPS. Northstar stores real financial data, so read the parts on HTTPS and backups before you rely on it.

The commands here assume you are in the folder that holds `compose.yaml`. Commands that start with `docker compose exec` or `run` run inside the container, and the rest run on the host.

## Install

Make a folder, put the two files in it, and start the app:

```
mkdir northstar && cd northstar
curl -O https://raw.githubusercontent.com/declankenny/northstar/main/compose.yaml
curl -o .env https://raw.githubusercontent.com/declankenny/northstar/main/.env.example
```

Open `.env` and set `TZ` to your timezone (a name such as `America/Chicago`). "Today" in Northstar is the date in that timezone, and it decides which accounts count as stale. The first time Northstar starts it saves `TZ` as the system property `system.timezone`, and after that you change the zone under Admin, System properties, not in `.env`. Then:

```
docker compose up -d
docker compose ps
```

After about a minute `docker compose ps` shows the container as `healthy`. There is no default user, so the first start prints a one-time setup token in the log. Show it:

```
docker compose logs northstar
```

Look for the line that begins "Northstar has no administrator yet" and copy the token under it. Then open <http://localhost:8000/setup>, paste the token, and fill in one form: your name, email and password (at least 12 characters), the household reporting currency, the default number and date format, and the time zone. The currency is the one every amount is in. It is chosen once and **cannot be changed after setup**, so choose it carefully. The form saves the administrator and those settings together, and then you sign in with the new account.

The token stops working when setup is finished. Restarting Northstar before then ends it and prints a new one, so run `docker compose logs northstar` again. A setup page left open for 30 minutes asks for the token again and keeps what you typed, except the password. Five wrong tokens in 15 minutes lock the page for a while. Until setup is finished, anyone who can read the log and reach the page can create the first administrator, so keep the log private and finish setup soon. Once an administrator exists, `/setup` goes to the sign-in page and no token is printed. An installation upgraded from 0.2 already has users, so it has no setup page and nothing changes for it, and one that has accounts has its system currency set to US dollars.

The app listens on `127.0.0.1` only, so you can reach it from this machine and nothing else can. That is on purpose: it serves plain HTTP, which is fine for trying it out and wrong for anything else, because a sign-in sends a password and a 30-day cookie. To use it from your phone or another computer, put it behind HTTPS as described next.

If sign-in appears to do nothing on an address such as `http://192.168.1.10:8000`, that is the cookie setting below doing its job: browsers drop a `Secure` cookie on plain HTTP, except on `localhost`. Use HTTPS, or for a trial on your own network set `NORTHSTAR_COOKIE_SECURE=0` in `.env` and accept the warning in the log.

## HTTPS with Traefik

Northstar does not do HTTPS itself. A reverse proxy does, and Traefik is shown here. Caddy and nginx work the same way: they pass requests to Northstar's port 8000 over a private Docker network, and Northstar is never published on a host port.

This assumes Traefik is already running with its Docker provider, a shared Docker network, an HTTPS entrypoint and a certificate resolver. The names below are placeholders: replace `NETWORK`, `ENTRYPOINT` and `CERT_RESOLVER` with the ones from your Traefik configuration, and the host name with yours.

Replace `compose.yaml` with this:

```yaml
services:
  northstar:
    image: ghcr.io/declankenny/northstar:latest
    restart: unless-stopped
    environment:
      TZ: ${TZ:-UTC}
      NORTHSTAR_COOKIE_SECURE: "1"
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:?set the proxy network in .env}
    volumes:
      - northstar-data:/data
    networks:
      - proxy
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    labels:
      - traefik.enable=true
      - traefik.docker.network=NETWORK
      - traefik.http.routers.northstar.rule=Host(`northstar.example.com`)
      - traefik.http.routers.northstar.entrypoints=ENTRYPOINT
      - traefik.http.routers.northstar.tls.certresolver=CERT_RESOLVER
      - traefik.http.routers.northstar.middlewares=northstar-hsts
      - traefik.http.middlewares.northstar-hsts.headers.stsSeconds=31536000
      - traefik.http.services.northstar.loadbalancer.server.port=8000

networks:
  proxy:
    external: true
    name: NETWORK

volumes:
  northstar-data:
```

Find the address range of the proxy network and put it in `.env`:

```
docker network inspect NETWORK --format '{{ (index .IPAM.Config 0).Subnet }}'
```

```
FORWARDED_ALLOW_IPS=172.18.0.0/16
```

Why each part is there:

- **No `ports:` line.** Only Traefik can reach the app, over the shared network.
- **`NORTHSTAR_COOKIE_SECURE: "1"`** marks the sign-in cookie `Secure`, so a browser never sends it over plain HTTP. It must be exactly `1`.
- **`FORWARDED_ALLOW_IPS`** tells the app which proxy to believe about visitors' real addresses. The limit on failed sign-ins per address needs them: without it every visitor looks like the proxy, so the app switches that limit off and logs a warning. Set it to the proxy's address or network, never to `*`, because anyone could then claim to be any address.
- **The `headers` middleware** adds HSTS, which tells browsers to use HTTPS for this host for a year. Northstar leaves HSTS to the proxy, because only the proxy knows the host is HTTPS for good. Only turn it on once HTTPS works.
- **Redirecting HTTP to HTTPS** is configured on Traefik's entrypoints, not here.

Start it with `docker compose up -d`, sign in over `https://`, and check that the log has no warning from Northstar:

```
docker compose logs northstar
```

## Where the data lives

The compose file keeps the database in a Docker volume called `northstar-data`, which needs no setup. If you would rather keep it in a folder you can see and back up, replace the volume with a bind mount (`./data:/data`). The container runs as UID 1000, not as root, so that folder must belong to that user or the app cannot write to it:

```
mkdir data
sudo chown 1000:1000 data
```

## Settings

Everything is set in `.env` beside the compose file, and every setting has a default, so the file may be empty.

| Setting | Default | What it does |
| --- | --- | --- |
| `TZ` | `UTC` | The household's timezone, used once: the first time Northstar starts it is saved as the system property `system.timezone`, which then decides what "today" is, which balance dates are allowed, and which accounts are stale. Changing `TZ` later has no effect, and the log warns when it differs from the property. |
| `NORTHSTAR_PORT` | `8000` | The port on this machine where the app listens, on `127.0.0.1` only. Only the compose file reads it, and the proxy example above does not use it. |
| `NORTHSTAR_COOKIE_SECURE` | `1` in the compose files | Marks the sign-in cookie `Secure`. The value must be exactly `1`: anything else counts as off, and the app logs a warning at startup. Without the compose file the app's own default is off. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | The reverse proxy whose forwarded addresses are believed, as an address or a network. Leave it alone when there is no proxy. |
| `NORTHSTAR_DB` | `/data/northstar.db` in the image | Where the database file is. The image sets it, and you should not need to. |
| `NORTHSTAR_PUBLIC_URL` | unset | The address people use to reach Northstar, such as `https://northstar.example.com`, for OIDC sign-in. HTTPS, with no path. Plain `http://` is accepted only for `localhost`, `127.0.0.1` and `[::1]`. It is never worked out from request headers. Not in the compose file: add it to the service's `environment:`. OIDC sign-in cannot be turned on without it. |
| `NORTHSTAR_OIDC_CLIENT_SECRET_FILE` | unset | The path of a file inside the container that holds the OIDC client secret, for example a Docker secret under `/run/secrets/`. Set this or `NORTHSTAR_OIDC_CLIENT_SECRET`, not both: Northstar will not start if both are set. The secret is never shown, logged or kept in the database. |
| `NORTHSTAR_OIDC_CLIENT_SECRET` | unset | The OIDC client secret itself, as an alternative to the file. Prefer the file, because an environment variable shows in `docker inspect`. |

## Upgrading

1. Read the section of [CHANGELOG.md](../CHANGELOG.md) for the new version. Every release has a **Breaking** heading that says what the upgrade means for the database, the settings and the backup format.
2. For a change you are nervous about, take a backup yourself first (see below).
3. Pull and restart:

   ```
   docker compose pull
   docker compose up -d
   docker compose ps
   ```

The image is `latest` in the example, which moves to each new release. For an install you can reproduce exactly, pin the image by its digest as well as its tag (`ghcr.io/declankenny/northstar:0.1.0@sha256:...`): `docker image inspect --format '{{index .RepoDigests 0}}' ghcr.io/declankenny/northstar:0.1.0` prints it. You then update by changing the line yourself. Before 1.0 a new minor version (0.1 to 0.2) can contain breaking changes, so if you want only fixes, use `ghcr.io/declankenny/northstar:0.1` instead. Only the latest minor version gets fixes.

**The app protects your data on its own.** If an upgrade has a database change to apply, Northstar first writes a checked backup of the database as it is, to `/data/backups/pre-migration-<version>-<UTC time>.db`, and only then changes it. The version in the name is the new one, the one that made the backup. The newest five are kept. If the backup fails, the app refuses to start and leaves the database alone. If the database was last used by a newer version than the one you are running, the app also refuses to start, and says so in the log (`docker compose logs northstar`).

### Upgrading from 0.2 to 0.3

Version 0.3 adds currencies, number and date formats, exchange rates and the first-run setup page. What an upgrade does to an installation that already runs 0.2:

- **A checked backup is made first**, as for any database change (see above), and the app starts only if it worked.
- **Installations with at least one account** get US dollars as the system currency, locked, because every existing amount is a dollar amount. Your accounts and balances are unchanged and are now US dollar accounts.
- **Installations with no account** have no system currency yet. Until an admin chooses one under Admin, System properties, no account can be added, and the Add account dialog says so. The currency is chosen once and cannot be changed afterwards.
- **Nobody sees the setup page**: you already have an administrator, so `/setup` goes to the sign-in page and no token is printed. Everyone keeps US English formats until they choose another on their profile, and an admin can set the default for new users.
- **Your `TZ` is saved once** as the system time zone, so "today" stays what it was. After that, change it under Admin, System properties.
- **Northstar now makes one outbound request a day**, to `api.frankfurter.dev` over HTTPS, at 18:00 in your time zone, for exchange rates. It sends only currency codes and dates. It does nothing until you enable a currency other than the system currency, and clearing `currency.rate.fetch_time` under System properties turns it off completely. See "Exchange rates" below.
- **The old `users create` command is gone.** Add users on the Users page.

### Rolling back

You can't just start the old image on an upgraded database, because it doesn't understand the new schema. Restore the backup the upgrade made, under the old image. The file name has the version that made it and the UTC time, so take the newest one from the list:

```
docker compose stop
docker compose run --rm northstar ls /data/backups
docker compose run --rm northstar python -m northstar.backup restore /data/backups/pre-migration-0.3.0-20261120-100000.db --replace
```

Then change the `image:` line back to the old version, for example `ghcr.io/declankenny/northstar:0.1`, and run `docker compose up -d`. The restore moves the upgraded database aside as `northstar.db.before-restore-<time>` and never deletes it. Anything you entered after the upgrade is not in the backup.

## Backup and restore

A backup is a complete copy of your financial data, with the password hashes and sessions, so keep it private. Never copy the database file by hand while the app runs: use the tool, which is safe on a running app and checks what it wrote.

Take a backup. The tool never overwrites a file, so the name includes the time:

```
docker compose exec northstar sh -c 'mkdir -p /data/manual && python -m northstar.backup create /data/manual/northstar-$(date +%F-%H%M).db'
```

A copy on the same disk does not survive the disk. Copy it to another machine, for example:

```
docker compose cp northstar:/data/manual/. ./backups
```

### Scheduling

Northstar's own scheduler runs only the application's own jobs, and backups stay on the host, so use your host's scheduler for them. Save this as `backup.sh` beside `compose.yaml`, make it executable, and change the last line to wherever your off-machine copy goes:

```sh
#!/bin/sh
set -e
cd "$(dirname "$0")"
docker compose exec -T northstar sh -c 'mkdir -p /data/manual && python -m northstar.backup create /data/manual/northstar-$(date +%F-%H%M).db && find /data/manual -name "northstar-*.db" -mtime +30 -delete'
docker compose cp northstar:/data/manual/. /path/to/a/copy/on/another/machine
```

Then run it every night with `crontab -e`:

```
15 3 * * * /opt/northstar/backup.sh
```

This keeps 30 days of backups in the container's volume and copies them out. A backup that you have never restored is a hope, so try a restore once.

### Restoring

The app must be stopped. Put the backup file in the volume if it is not there already, then restore it over the database:

```
docker compose stop
docker compose cp ./northstar-2026-11-01.db northstar:/data/manual/
docker compose run --rm northstar python -m northstar.backup restore /data/manual/northstar-2026-11-01.db --replace
docker compose start
```

The backup is checked before anything changes. The database it replaces is moved aside as `northstar.db.before-restore-<time>` in the same volume, never deleted.

## Exchange rates

Northstar fetches exchange rates for you once a day, from [Frankfurter](https://frankfurter.dev/), which publishes central-bank rates. The container needs to reach `api.frankfurter.dev` over HTTPS. A request carries only currency codes and dates, never an amount, an account or a name. The time of day is the system property `currency.rate.fetch_time` under Admin, System properties (18:00 in the time zone set in `system.timezone` until you change it), and clearing it turns automatic fetching off. A currency's page under Admin, Currencies shows when it runs and how the last run went. The fetch only adds dates that have no rate, so a rate you typed or corrected is never replaced, and a currency Frankfurter does not list is skipped, so enter its rates by hand. It is the only request Northstar makes to another host, and a deployment that must not call out clears `currency.rate.fetch_time`. To fetch now, for example the first time after you enable a currency, run:

```sh
docker compose exec northstar python -m northstar.rates fetch
```

It prints `Rates fetched.` when it worked. If a run fails, the next day's run tries again from where it stopped.

## Users and passwords

Admins add and remove users, and manage account types, from the app, and the first admin is made on the setup page. Everyone who signs in sees all the household's data. The command line lists users and resets a password, which is the way back in if an admin forgets theirs:

```
docker compose exec northstar python -m northstar.users list
docker compose exec northstar python -m northstar.users set-password name@example.com
```

`set-password` asks for the new password and signs that user out everywhere. There is no command that creates a user: use the Users page.

If password sign-in has been switched off (the system property `system.auth.local.enabled`) and the identity provider is down or misconfigured, this turns it back on. It needs only the database, so it works with no provider and no signed-in session:

```
docker compose exec northstar python -m northstar.signin enable-local
```

Then sign in with a password. If an admin has none, give them one with `set-password`.

**If no active admin remains at all** (every admin was deleted), there is no command to make one, and the setup page stays closed on purpose, because it counts deleted admins so that deleting one can never open it to a stranger. The way back is to restore a backup taken while an admin existed (see "Restoring"). Anything entered after that backup is lost, which is the reason to keep recent backups. A command that recovers without a restore is planned ([issue 158](https://github.com/declankenny/northstar/issues/158)).

Passwords need at least 12 characters. They are hashed with scrypt, which is deliberately slow and memory-hungry: a sign-in takes about half a second and 128 MiB, more time on a small device such as a Raspberry Pi, and at most two run at the same time.

### Limits on failed sign-ins

A person who gets the password wrong is limited: 5 attempts in 15 minutes per email from one address, 30 an hour per email from any address, and 20 in 15 minutes per address. A blocked attempt says how long to wait and does not check the password, so waiting is the only fix, and there is no lock-out to undo. Changing a password through the app has the same limit on a wrong current password.

## Known behaviour

- **Two people editing the same balance at the same moment:** the second save is refused, nothing is written, and the screen says who changed it and shows what it is now, so the person decides. Adding a balance on a date that already has one replaces it.
- **Sessions last 30 days** from sign-in, and are not extended by use.
- **Every account has one currency,** chosen when it is created and never changed. Household totals are in the system currency, converted with the latest exchange rate on or before each date. A date on which an account has no rate has no net worth, and the app says which currencies need one.
- **Crypto is not a currency here.** Enter a balance held in crypto as its value in the system currency at the time.
- **The secure cookie on `http://localhost`** has been checked in a Chromium-based browser only. Other browsers may behave differently, and if sign-in fails on `localhost`, set `NORTHSTAR_COOKIE_SECURE=0`.

## Where to get help

Report a bug in an issue, with your version (shown at the bottom of the left-hand menu) and what you did, and with synthetic data only. Report a security problem privately, as described in [SECURITY.md](../SECURITY.md).

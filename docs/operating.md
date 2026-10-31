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

Open `.env` and set `TZ` to your timezone (a name such as `America/Chicago`). "Today" in Northstar is the date in that timezone, and it decides which accounts count as stale. Then:

```
docker compose up -d
docker compose ps
```

After about a minute `docker compose ps` shows the container as `healthy`. There is no default user, so create the first admin. The command asks for the password twice, and it must be at least 12 characters:

```
docker compose exec northstar python -m northstar.users create you@example.com "Your Name" --admin
```

Then open <http://localhost:8000>. The app listens on `127.0.0.1` only, so you can reach it from this machine and nothing else can. That is on purpose: it serves plain HTTP, which is fine for trying it out and wrong for anything else, because a sign-in sends a password and a 30-day cookie. To use it from your phone or another computer, put it behind HTTPS as described next.

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
| `TZ` | `UTC` | The household's timezone. It decides what "today" is, which balance dates are allowed, and which accounts are stale. |
| `NORTHSTAR_PORT` | `8000` | The port on this machine where the app listens, on `127.0.0.1` only. Only the compose file reads it, and the proxy example above does not use it. |
| `NORTHSTAR_COOKIE_SECURE` | `1` in the compose files | Marks the sign-in cookie `Secure`. The value must be exactly `1`: anything else counts as off, and the app logs a warning at startup. Without the compose file the app's own default is off. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | The reverse proxy whose forwarded addresses are believed, as an address or a network. Leave it alone when there is no proxy. |
| `NORTHSTAR_DB` | `/data/northstar.db` in the image | Where the database file is. The image sets it, and you should not need to. |

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

### Rolling back

You can't just start the old image on an upgraded database, because it doesn't understand the new schema. Restore the backup the upgrade made, under the old image:

```
docker compose stop
docker compose run --rm northstar ls /data/backups
docker compose run --rm northstar python -m northstar.backup restore /data/backups/pre-migration-0.2.0-20261101-100000.db --replace
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

Northstar has no scheduler of its own, so use your host's. Save this as `backup.sh` beside `compose.yaml`, make it executable, and change the last line to wherever your off-machine copy goes:

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

## Users and passwords

Admins add and remove users, and manage account types, from the app. Everyone who signs in sees all the household's data. These commands do the same from the command line, and are the way back in if every admin is locked out:

```
docker compose exec northstar python -m northstar.users list
docker compose exec northstar python -m northstar.users create name@example.com "Their Name"
docker compose exec northstar python -m northstar.users set-password name@example.com
```

`set-password` signs that user out everywhere. Add `--admin` to `create` to make an admin.

Passwords need at least 12 characters. They are hashed with scrypt, which is deliberately slow and memory-hungry: a sign-in takes about half a second and 128 MiB, more time on a small device such as a Raspberry Pi, and at most two run at the same time.

### Limits on failed sign-ins

A person who gets the password wrong is limited: 5 attempts in 15 minutes per email from one address, 30 an hour per email from any address, and 20 in 15 minutes per address. A blocked attempt says how long to wait and does not check the password, so waiting is the only fix, and there is no lock-out to undo. Changing a password through the app has the same limit on a wrong current password.

## Known behaviour

- **Two people editing the same balance at the same moment: the last save wins.** The Update balances screen only saves the amounts you changed, so it will not overwrite other rows, but a balance edited by two people at once keeps the later change. Detecting this is planned ([issue 10](https://github.com/declankenny/northstar/issues/10)).
- **Sessions last 30 days** from sign-in, and are not extended by use.
- **Amounts are US dollars,** as dollars and cents.
- **The secure cookie on `http://localhost`** has been checked in a Chromium-based browser only. Other browsers may behave differently, and if sign-in fails on `localhost`, set `NORTHSTAR_COOKIE_SECURE=0`.

## Where to get help

Report a bug in an issue, with your version (shown at the bottom of the left-hand menu) and what you did, and with synthetic data only. Report a security problem privately, as described in [SECURITY.md](../SECURITY.md).

# Changelog

All notable changes to Northstar are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and the project follows [Semantic Versioning](https://semver.org/). Before 1.0 anything may change between minor versions.

Each released version has a **Breaking** heading that says what an upgrade means for the database (migrations), the environment variables and the backup format. Those three always count as breaking before 1.0. If it says "Nothing", an upgrade needs no action beyond pulling the new image.

## [Unreleased]

### Added

- A roadmap, `docs/roadmap.md`, that sets out where Northstar is going, what 1.0 will promise, and why the planned releases come in their order. The releases themselves are GitHub milestones.

## [0.1.0] - 2026-10-31

The first release.

### Breaking

Nothing: this is the first version, so there is nothing to upgrade from.

### Added

- Accounts of two classes, Asset and Liability, with types that admins manage, and a way to close an account without losing its history.
- Dated balances for each account, entered by hand, with one screen to update many accounts at once.
- Net worth over time and per-account balance history, as charts and tables.
- Local sign-in for a household, with admins and ordinary users and a light or dark theme.
- Limits on failed sign-ins, a strict content security policy, and password hashing that is upgraded automatically when its cost is raised.
- A command to back up and restore the database (`python -m northstar.backup`).
- A checked backup before any database migration, in a `backups` folder beside the database (the newest five are kept), and a refusal to start on a database that a newer version has migrated.
- A published Docker image, a compose file that uses it, and a health check.
- An operator guide (`docs/operating.md`): installing, HTTPS with Traefik, every setting, upgrading and rolling back, and backup and restore.

### Configuration

- `NORTHSTAR_DB`: the database file. The image sets it to `/data/northstar.db`.
- `NORTHSTAR_COOKIE_SECURE`: set to `1` when the app is served over HTTPS. The compose file defaults it to `1`.
- `FORWARDED_ALLOW_IPS`: the reverse proxy to trust, for the real visitor addresses.
- `TZ`: the household's timezone, which decides what "today" is.

# Changelog

All notable changes to Northstar are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and the project follows [Semantic Versioning](https://semver.org/). Before 1.0 anything may change between minor versions.

Each released version has a **Breaking** heading that says what an upgrade means for the database (migrations), the environment variables and the backup format. Those three always count as breaking before 1.0. If it says "Nothing", an upgrade needs no action beyond pulling the new image.

## [Unreleased]

### Added

- System properties (#124): an admin page, System properties under Admin in the sidebar, for settings that belong to the whole installation. Properties are listed by group on the left and edited one at a time on the right, with a hint beside each name, Save and Revert on a changed value, and the reason shown when a value is refused. Every change is in the change log. The first properties are `ui.theme.default`, which sets the theme every new user starts with (whether added from the page, the command line or by reactivating a deleted user), `balance.stale`, which sets the stale-after days the Add type form starts at, and `system.currency`, which nothing reads yet.

### Breaking

- Migrations: four new tables hold the system properties, and the first three properties are added. A checked backup is made first. Nothing else changes for an existing installation, and there are no new environment variables and no change to the backup format.

### Changed

- The Add type form starts a new account type at the `balance.stale` system property, 35 days until an admin changes it, where the 35 was fixed in the form. Existing types keep their own days, and any number of at least 1 can still be typed.
- The sidebar and the sign-in page show the new brand mark in place of the plain star (#76), as a pair of images that follows the theme you chose in Northstar, not the operating system's: a white road on a blue tile on the light theme, and a blue road on a white tile on the dark one. The browser tab icon is unchanged.
- The sign-in page is now a page of the React app (#65), and the app's files under `/assets/` are public so it can load. Signing in and signing out go through `/api/auth/login` and `/api/auth/logout`, which answer JSON, and the page goes on with a full page load. The look, the throttling, the cookie and the content security policy are unchanged. Signing in now needs JavaScript, as the rest of the app already did.
- Two dependencies are gone: `jinja2`, which only rendered the old sign-in page, and `python-multipart`, which only read its form.

## [0.2.0] - 2026-11-03

Import and export of balances as CSV, a change log with an admin register of imports and undo of an import, and a refusal when two people change the same balance. The runtime is now Python 3.15.

### Added

- A register of past imports for admins (#81): Imports under Admin in the sidebar lists each import's date, who made it, the account, the file name and how many balances it added and replaced. Each import that nothing has changed since can be undone from there (admins only): the balances it added are deleted and the ones it replaced get their old amounts back, or, if any of them has been changed since or the account is closed, the undo says which dates are in the way and changes nothing. The import review no longer says an import cannot be undone.
- Export one account's balances as a CSV file (#80): Export CSV on an account's page and in its ⋯ menu on the Accounts list. The file has the columns Account ID, Account Name, Balance Date and Balance Amount, oldest first, and importing it back into the same account finds every balance unchanged. Importing also recognises "Balance Amount" as a balance column.
- Import dated balance history from a CSV file into one account (#79): Import CSV… on an account's page and in its ⋯ menu on the Accounts list. Choose the file, map its columns, review exactly what will be added, replaced or skipped, then import. Semicolon and tab files, European number and date styles, and amounts in parentheses are understood, the date format is chosen when a file could be read two ways, and nothing is written until the final step. Importing cannot be undone yet.
- Account names are unique, and adding or renaming to a taken name says so, including when a closed account holds it (#82).
- A migration runner that can rebuild tables safely, with foreign keys off and checked before commit, as groundwork for the v0.2 schema changes (#85).
- A roadmap, `docs/roadmap.md`, that sets out where Northstar is going, what 1.0 will promise, and why the planned releases come in their order. The releases themselves are GitHub milestones.

### Changed

- The runtime moved from Python 3.14 to 3.15 (#72): the image, CI and the README together, and the minimum Python version in `pyproject.toml` is now 3.15. Running from source needs Python 3.15.
- Two people changing the same balance no longer silently overwrite each other (#10): editing or deleting a balance, or saving it on Update balances, is refused if it has been changed, deleted or added since you opened it. The message says what it is now and who changed it, and the edit dialog can show the current value. The Update screen keeps what you typed, marks the rows that changed, and saves them when you press Save again.
- Removed the redundant Update balances button from the dashboard header; Update balances remains available in the left-hand navigation (#78).

### Breaking

- Migrations: every change to an account, account type, balance or user is now recorded in a change log (four new tables), and balances gain a `version` column. Nothing in the app shows the log yet, and existing data gets no entries. A checked backup is made first, and the change log grows with use, so backups get a little larger.
- Migrations: deleting an account no longer erases its balances. The account is marked deleted and, with its balances, disappears from every screen and from net worth history, exactly as before, but the data stays in the database for a later restore. A deleted account frees its name. A type that only deleted accounts use can't be deleted until restoring exists. A checked backup is made first.
- Migrations: users are no longer erased when deleted: they are marked deleted, cannot sign in and are hidden, and adding their email again restores the same user with the name, password and admin setting you enter. A checked backup is made first.
- Migrations: every table gets audit columns (who and when created and last changed), a system user is added to the users table, ids are never reused, and the session and sign-in attempt tables are renamed `sys_sessions` and `sys_login_attempts`. Existing rows are attributed to the system user. A checked backup is made first, and rolling back to an older image needs it restored. The system user is hidden and cannot sign in; no user may have an email ending in `.invalid`.
- Migrations: account names are now unique, ignoring case, across open and closed accounts. An existing database with duplicate names keeps the lowest id's name and renames each later duplicate to "Name (2)", "Name (3)" and so on (the smallest number no account uses), so check your account list after upgrading. A checked backup is made first.
- Migrations: the record of applied migrations is renamed from `schema_migrations` to `sys_schema_migrations` the first time this version starts, after a checked backup in `backups/`. Rolling back to an older image needs that backup restored, as for any migration. No environment variable changes, and backups made before the upgrade still restore.

## [0.1.1] - 2026-11-01

Fixes to backup, restore and the sign-in page.

### Breaking

Nothing: no migrations, no environment variables and no change to the backup format.

### Fixed

- Restoring twice within the same second no longer overwrites the database the first restore set aside. Each gets its own name, with `-2`, `-3` and so on added when needed (#54).
- A backup that records a migration but is missing the table it creates, such as `login_attempts`, is now refused, instead of being restored and then failing at the first sign-in. Backups made before a migration remain valid (#53).
- The sign-in page and the app now have a browser tab icon. The icon files are served from `/static/` without signing in (#50).

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

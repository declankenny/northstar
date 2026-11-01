# Northstar: specification

Status: version 0.x, so anything may change between minor versions. Northstar tracks a household's net worth over time from balances entered by hand, and every feature described here is built.

This file records what the code cannot tell you: what Northstar is for, what it will and will not do, and the rules its data must obey. The reasons behind decisions are in `decisions.md`, and what is planned but not built is in `roadmap.md`. Screens, layouts and endpoints are not described anywhere in prose: the code and its tests are the reference. A change to a rule here ships in the same pull request as the code. Anything marked TODO is unresolved: do not guess it.

## Purpose

Track a household's financial position over time. Northstar records dated balances for each account and shows net worth and per-account history. Entry is manual.

## Scope

**Included**

- Accounts with a name, a class (Asset or Liability) and a configurable type.
- Dated balances per account, entered by hand, with one way to update many accounts at once.
- Net worth over time and per-account balance history, as charts and tables.
- Closing an account to declutter, without losing its history.
- Local sign-in for a household: admins and ordinary users, a light or dark theme.

**Not included yet**

These are left out of the current release to keep it focused, not ruled out. Their GitHub milestones say when, and `roadmap.md` says why.

- CSV import and export.
- Multiple currencies and locale-aware number and date formatting. Until then, every amount is US dollars in integer cents and no currency is stored. A balance held in another currency or in crypto is entered as its US dollar value at the time. Existing balances stay valid when currencies arrive because they are US dollars.
- Transactions, opening balances and reconciliation.
- Bank feeds, starting with SimpleFIN.
- Budgets and categories.
- Savings goals (backlog: might be done, not yet scheduled).
- Loan schedules. A loan is a liability with a balance history.

**Not planned**

- Investment positions or holdings, tax reporting and bill payment. Each would need a concrete use case and its own design.

## Data model

**account_classes**: id, name. Exactly two rows, Asset and Liability, loaded when the database is created and not editable.

**account_types**: id, name, class_id, stale_after_days (whole days, at least 1), created_at. Admins add, rename and delete types. Starting list: assets are checking, savings, brokerage, retirement, other investment, real estate and other asset. Liabilities are credit card, loan, mortgage and other liability.

**accounts**: id, name, class_id, type_id, is_open (default true), notes (optional), created_at. The pair (type_id, class_id) must match a row in account_types, enforced by a composite foreign key, so an account's type always belongs to its class.

**balances**: id, account_id, as_of_date, amount_cents (integer), note (optional), source ("manual" now, which leaves room for a feed), created_at, updated_at. One balance per account per date.

**users** and **sessions** hold sign-in (see "Security"). A user has an email, display name, password hash, admin flag and theme.

## Rules

- **Money**: amounts are integer cents, never floating point. They are typed as dollars and cents, such as 1,234.56 or -25.00. More than two decimal places is refused, and so is an amount over about $100 billion.
- **Dates**: a balance date is a calendar date with no timezone, and cannot be in the future (in a manual tracker that is almost always a typo). The app has no timezone logic. "Today" is the date on the machine running the app, read in one `today()` function so tests can fix it, and a deployment sets the container's timezone with the standard `TZ` variable. Row timestamps are stored in UTC.
- **Sign convention**: balances are stored as entered, the way a statement shows them, and the account's class says what they mean. A 250,000.00 mortgage is 25000000 on a liability account. Net worth is the sum of asset balances minus the sum of liability balances. A balance may be negative on either side (an overdrawn checking account, an overpaid card) and net worth needs no special case.
- **Net worth is one calculation**: `net_worth_on(date)`. Every series, total and chart only chooses which dates to ask about, and the server computes every number, so no net worth rule lives in the frontend. A series never starts before the first balance, because before that net worth is zero only because nothing was entered, and drawing it would look like a climb from zero.
- **Carry-forward**: net worth on date D uses each account's latest balance on or before D. An account with no balance by D counts for nothing. An account that is not updated keeps its old balance (staleness is the safeguard), and a new account makes net worth step on the day it first appears unless an earlier-dated balance is entered.
- **Class and type**: every type belongs to a class, chosen when the type is created. An account's class can be edited at any time, and the edit must pick a type in the new class. It changes net worth for every past date the account covers, so the person is told how many balances and from when. There is no audit trail. A type's class cannot change while any account uses it.
- **Deleting**: deleting an account permanently deletes its balances and changes net worth history to match, and the person is told how many balances go. Closing is the way to hide an account and keep its history. A type can be deleted only while no account uses it, and the database refuses otherwise even if the app is bypassed, so deleting a type can never change financial history.
- **Closing**: an account can be closed only when its latest balance is zero or it has none, otherwise a final zero balance comes first (with a note, if the account left the household). Closed accounts leave balance entry and the everyday views, and stay visible in a closed list with their history. Net worth ignores whether an account is open, because carry-forward does the work: the final zero carries forward. Balances cannot be added, edited or deleted on a closed account until it is reopened. The close date is not stored, it is the date of the final zero.
- **Changing a balance**: a balance can be added, edited or deleted. Adding on a date that already has a balance replaces it. An edit that moves a balance onto a date the account already uses is refused. A note is optional, at most 500 characters.
- **Updating many balances**: one date for all accounts. A blank amount is skipped, and a zero must be typed. Saving a date that already has a balance edits it, and existing notes are left alone. Only the amounts the person changed are saved, so a row that was merely shown is never written back over someone else's change, and the form cannot be edited while a save or a date load is running. A save is all or nothing: if any amount is invalid nothing is saved and each bad row says why. Choosing another date writes nothing.
- **Staleness**: an open account is stale when the days from its latest balance to today exceed its type's `stale_after_days`. An open account with no balances is also flagged. Closed accounts are never flagged. A new type starts at 35 days. Starting values are 35 days for every starting type except real estate, which is 365. A type that changes rarely gets a large value, not a special "never stale" setting.

## Technical shape

- **Stack**: Python, FastAPI and SQLite on the server. The interface is a React and TypeScript single-page app built with Vite and served by the same application on the same origin, so there is no CORS. The sign-in page is the one page rendered by the server, from a template, because the app itself cannot be public.
- **Dependencies**: few, each with a stated reason, with versions pinned exactly. The pins include the base images (by digest) and the CI actions (by commit SHA). Dependabot proposes every update as a pull request, except a new major version of Node, which is moved to deliberately onto an LTS line. CI fails a pull request on a known vulnerability in the Python dependencies (`pip-audit`), in the frontend dependencies that ship in the bundle (`npm audit`), or in the built image (Trivy, HIGH and CRITICAL findings that have a fix). The same checks run weekly on `main`. The final image has no pip.
- **Architecture**: business logic lives in plain Python functions, separate from the routes. Routes call them and add no rules. The JSON API under `/api` is internal and not a stable contract.
- **Transactions**: any operation that reads in order to decide and then writes (closing an account, changing a balance, the admin rules, a password change) runs inside one `db.write_transaction`, which takes SQLite's write lock at the start, so two requests at the same moment cannot both pass the same check. Operations that need several writes to succeed together use the same helper.
- **Schema**: changes ship as forward-only migrations, tested on a copy of a database first. A released migration is never edited. Only the app migrates, when it starts. If a migration is pending it first writes a checked backup beside the database, to `backups/pre-migration-<version>-<UTC time>.db`, and does not start if that fails. The newest five of these are kept, and older ones are removed only after a migration has worked. A database that has migrations this version does not know, judged by the highest migration number, is refused with a message to run the newer version or restore a backup. The command line tools never change the schema: they refuse a database the app has not brought to this version.
- **Packaging**: one container and one SQLite file on a mounted volume.
- **Backup**: a live SQLite file is never copied by hand. `python -m northstar.backup create FILE` and `restore FILE [--replace]` use SQLite's online backup. A backup is checked and only then renamed into place, never overwrites a file, and leaves no partial file on failure. The check requires the tables that the migrations recorded in the file create, so a file that records a migration but lacks its table is refused, while a backup made before a migration is still valid. A restore needs the app stopped and moves the old database aside instead of deleting it, under a name that never replaces an earlier preserved file. The tool prints counts only. A backup holds real data, password hashes and sessions, so it stays out of any repository and in a private place. Northstar has no scheduler: the operator guide gives a script for the host's cron that takes a backup nightly, keeps 30 days in the volume and copies them to another machine, and the off-machine copy is the operator's job.
- **Frontend rules**: dates stay as `YYYY-MM-DD` strings and the frontend never creates a JavaScript `Date`, so the no-timezone rule holds. Money stays integer cents. Routing is a small history router with no library, on clean paths from the site root. The server returns the app for any page address, and the names `api`, `login`, `logout`, `static` and `assets` are reserved for the server, so a new top-level server route must avoid the page names. An address that is not a page shows a "Page not found" screen inside the app, with status 200, because the list of pages lives only in the frontend.

## Security

- **Access**: every address, the app and every `/api` endpoint needs a signed-in user. Only `/login` and the files under `/static/` (its stylesheet, the theme script and the icons) are public. Pages redirect to sign-in and keep the address asked for, and `/api` answers 401. Only a plain path on this site is kept: anything with a host, a scheme, a backslash, a space or a control character goes to the Dashboard instead.
- **Users and roles**: every signed-in user sees all household data, so there is no per-user data. Admins alone manage users and account types. There must always be at least one admin, you cannot delete yourself or remove your own admin, and a password reset or user deletion ends that person's sessions at once. An email is lower-cased and unique.
- **Passwords**: scrypt from the standard library at N=2^17, r=8, p=1 (128 MiB and about half a second per hash), at least 12 characters and no other composition rules. A hash carries its own cost, so the cost can be raised later: a hash made with a lower cost still verifies and is replaced by one at the current cost the next time its owner signs in, and a stronger one is never weakened. At most two hashes run at the same time, so a burst of sign-ins queues instead of using all the memory. A stored hash that asks for an unreasonable cost is refused without being computed. A wrong password and an unknown email give the same message and take about the same time (the hash for unknown emails is built at startup, so even the first miss costs the same). Changing or resetting a password ends the other sessions.
- **Sessions**: a random token in an `HttpOnly`, `SameSite=Lax` cookie, valid 30 days from sign-in and not extended on use. Only the token's SHA-256 is stored. The cookie is marked `Secure` when `NORTHSTAR_COOKIE_SECURE=1`, which must be set whenever the app is served over HTTPS, and the app logs a warning at startup when it is not (any value other than exactly `1` counts as not set). The app's own default is off, and the compose files default it to `1`. Any change made from a page of another site is refused.
- **Throttling**: failed sign-ins, and wrong guesses of the current password on Change password, are limited: 5 in 15 minutes per email from one address, 30 in an hour per email from any address, and 20 in 15 minutes per address for any email (the last only when the address can be trusted). A blocked attempt answers 429 with `Retry-After`, never checks the password, and is not recorded. Unknown emails are counted like real ones, and only hashes of the email and address are stored. Behind a reverse proxy, `FORWARDED_ALLOW_IPS` must list the proxy for the real addresses to be used. If it does not, the app notices, turns the address limit off, and logs a warning.
- **Headers**: every response carries a content security policy that allows only the app's own scripts, styles, images, fonts and connections, no inline script or style in HTML, no `eval`, no other site's content, and no framing of the pages, plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and a `Permissions-Policy` that turns off the camera, microphone, location, payment and USB. The pages must stay free of inline scripts, `style` attributes, style blocks and event handler attributes, and a test enforces it. The theme is applied by the file `static/theme.js`. HSTS is left to the reverse proxy.
- **First admin**: there is no default user or password. The first admin is created from the command line, once the app has started and set up the database, and the command asks for the password: `python -m northstar.users create EMAIL NAME --admin`. The same tool resets passwords and is the way back in if every admin is locked out.
- **HTTPS**: the app serves plain HTTP and expects a reverse proxy to provide HTTPS. The operator guide, `docs/operating.md`, includes a Traefik example with the network, entrypoint and certificate resolver names as placeholders, and says that plain HTTP is for trying the app out only.

## Release and distribution

Northstar is open source (MIT, copyright Declan Kenny) for other people to run themselves, so it must be secure by default, have defined releases and be easy to install and update.

- **Versions**: semantic versions. Before 1.0 anything may change, with notes, and database migrations, environment variables and the backup format always count as breaking. From 1.0, the compatibility promise in `roadmap.md` defines what is breaking. Migrations, environment variable changes and backup format changes are always in the release notes.
- **Branches**: `main` is development. `release/X.Y` is cut when `vX.Y.0` is tagged, starting with `release/0.1`. A fix lands on `main` first and is backported, and each release is a tag `vX.Y.Z`. Only the latest minor version gets fixes until 1.0. Once the repo is public, rulesets protect `main`, `release/*` and `v*` tags: a pull request and passing checks are required, with no force-push or deletion.
- **Version**: written once, as `version` in `pyproject.toml`. The app reads it from the installed package and shows it, and the image carries it as a label. Tests fail if the frontend package declares another version or the changelog has no section for it, and the release workflow refuses a tag that does not match it or a changelog section that still has a TODO date.
- **Changelog**: `CHANGELOG.md`, in the Keep a Changelog format, has a section per version with a **Breaking** heading that says what an upgrade means for migrations, environment variables and the backup format, which always count as breaking before 1.0. A release's section is its release notes.
- **Community files**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue templates for a bug and a feature request, and a pull request template with "What changed", "Verified" and "Not verified". Blank issues are off, and the issue chooser points security reports at private reporting.
- **Security policy**: `SECURITY.md` gives the supported versions, private reporting through GitHub, what to expect, the threat model and hardening notes for operators. Its threat model is the one in "Security" above: a household that trusts its own members.
- **Compose files**: `compose.yaml` is the user's file. It uses the published image with no `build:`, publishes the port on `127.0.0.1` only, keeps data in a named volume, drops all capabilities, and sets `NORTHSTAR_COOKIE_SECURE` to `1` by default. Its settings (`TZ`, `NORTHSTAR_PORT`, `NORTHSTAR_COOKIE_SECURE`) come from a `.env` beside it, and `.env.example` lists them with their defaults. The developer build is `compose.dev.yaml`. The image runs as UID 1000 and has a health check that requests the sign-in page.
- **Publishing**: pushing a tag `vX.Y.Z` (or `vX.Y.Z-rc.N` for a release candidate) runs the release workflow. It refuses to publish unless the tag matches the version in `pyproject.toml` and `frontend/package.json` (a release candidate is `X.Y.ZrcN` in Python and `X.Y.Z-rc.N` in npm), `CHANGELOG.md` has a section for the version (a final release also needs a real date, not a TODO), the tagged commit is on `main` or a `release/*` branch, the tests and the image scan pass again, and that version has not been published before. It then pushes the image `ghcr.io/declankenny/northstar` for amd64 and arm64 with build provenance, tagged `X.Y.Z` (never reused) and, when no higher version holds them, `X.Y` and `latest`, and creates a GitHub Release whose notes are the changelog section. A release candidate gets only its own tag and is marked as a pre-release. The package must be public, which is a one-time setting on GitHub that the workflow cannot make. Updating is `docker compose pull && docker compose up -d`. A rollback is a restore of the pre-migration backup under the old image. The project keeps a `CHANGELOG`, a README quick start for trying it out and developing, and the operator guide `docs/operating.md` for installing, securing, upgrading and backing up a real installation.

## Acceptance for v0.1.0

- Accounts of every type can be created, and balances entered on arbitrary dates.
- Net worth on each date, and the month-end series built from it, match a hand calculation on a small synthetic dataset (automated test).
- Updating ten accounts takes one screen and one submit.
- Data survives a container restart, and a backup and restore has been tested.
- Tests use synthetic data only.
- Everything under "Release and distribution" is built, the image is published, and an install and an upgrade have been rehearsed from the published image on a clean machine.

## Roadmap

What is planned but not built, and why, is in `roadmap.md`, which also says how the roadmap is kept in GitHub milestones and issues. A planned feature moves into this file in the pull request that builds it.

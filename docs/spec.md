# Northstar: specification

Status: pre-release. Northstar tracks a household's net worth over time from balances entered by hand, and every feature described here is built. The first release, v0.1.0, is waiting on the security work under "Release and distribution".

This file records what the code cannot tell you: what Northstar is for, what it will and will not do, and the rules its data must obey. The reasons behind decisions are in `decisions.md`. Screens, layouts and endpoints are not described anywhere in prose: the code and its tests are the reference. A change to a rule here ships in the same pull request as the code. Anything marked TODO is unresolved: do not guess it.

## Purpose

Track a household's financial position over time. Northstar records dated balances for each account and shows net worth and per-account history. Entry is manual.

## Scope

**Included**

- Accounts with a name, a class (Asset or Liability) and a configurable type.
- Dated balances per account, entered by hand, with one way to update many accounts at once.
- Net worth over time and per-account balance history, as charts and tables.
- Closing an account to declutter, without losing its history.
- Local sign-in for a household: admins and ordinary users, a light or dark theme.

**Not included**

- Transactions, opening balances and reconciliation.
- Investment positions or holdings.
- Budgets, categories and goals.
- Bank feeds. SimpleFIN is the first planned addition (see "Roadmap").
- Multiple currencies. Every amount is US dollars in integer cents and no currency is stored. A balance held in another currency or in crypto is entered as its US dollar value at the time. Supporting currencies later means a currency on each account, a rate per balance and rounding rules, which is a separate design. Existing balances stay valid because they default to USD.
- Loan schedules. A loan is a liability with a balance history.

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
- **Dependencies**: few, each with a stated reason, with versions pinned exactly. The pins include the base images (by digest) and the CI actions (by commit SHA). Dependabot proposes every update as a pull request, and CI fails a pull request on a known vulnerability in the Python dependencies (`pip-audit`), in the frontend dependencies that ship in the bundle (`npm audit`), or in the built image (Trivy, HIGH and CRITICAL findings that have a fix). The same checks run weekly on `main`. The final image has no pip.
- **Architecture**: business logic lives in plain Python functions, separate from the routes. Routes call them and add no rules. The JSON API under `/api` is internal and not a stable contract.
- **Transactions**: any operation that reads in order to decide and then writes (closing an account, changing a balance, the admin rules, a password change) runs inside one `db.write_transaction`, which takes SQLite's write lock at the start, so two requests at the same moment cannot both pass the same check. Operations that need several writes to succeed together use the same helper.
- **Schema**: changes ship as forward-only migrations, tested on a copy of a database first. A released migration is never edited.
- **Packaging**: one container and one SQLite file on a mounted volume.
- **Backup**: a live SQLite file is never copied by hand. `python -m northstar.backup create FILE` and `restore FILE [--replace]` use SQLite's online backup. A backup is checked and only then renamed into place, never overwrites a file, and leaves no partial file on failure. A restore needs the app stopped and moves the old database aside instead of deleting it. The tool prints counts only. A backup holds real data, password hashes and sessions, so it stays out of any repository and in a private place.
- **Frontend rules**: dates stay as `YYYY-MM-DD` strings and the frontend never creates a JavaScript `Date`, so the no-timezone rule holds. Money stays integer cents. Routing is a small history router with no library, on clean paths from the site root. The server returns the app for any page address, and the names `api`, `login`, `logout`, `static` and `assets` are reserved for the server, so a new top-level server route must avoid the page names. An address that is not a page shows a "Page not found" screen inside the app, with status 200, because the list of pages lives only in the frontend.

## Security

- **Access**: every address, the app and every `/api` endpoint needs a signed-in user. Only `/login` and its stylesheet are public. Pages redirect to sign-in and keep the address asked for, and `/api` answers 401.
- **Users and roles**: every signed-in user sees all household data, so there is no per-user data. Admins alone manage users and account types. There must always be at least one admin, you cannot delete yourself or remove your own admin, and a password reset or user deletion ends that person's sessions at once. An email is lower-cased and unique.
- **Passwords**: scrypt from the standard library, at least 12 characters and no other composition rules. A wrong password and an unknown email give the same message and take about the same time. Changing or resetting a password ends the other sessions.
- **Sessions**: a random token in an `HttpOnly`, `SameSite=Lax` cookie, valid 30 days from sign-in and not extended on use. Only the token's SHA-256 is stored. The cookie is marked `Secure` when `NORTHSTAR_COOKIE_SECURE=1`, which must be set whenever the app is served over HTTPS. Any change made from a page of another site is refused.
- **Throttling**: failed sign-ins, and wrong guesses of the current password on Change password, are limited: 5 in 15 minutes per email from one address, 30 in an hour per email from any address, and 20 in 15 minutes per address for any email (the last only when the address can be trusted). A blocked attempt answers 429 with `Retry-After`, never checks the password, and is not recorded. Unknown emails are counted like real ones, and only hashes of the email and address are stored. Behind a reverse proxy, `FORWARDED_ALLOW_IPS` must list the proxy for the real addresses to be used. If it does not, the app notices, turns the address limit off, and logs a warning.
- **Headers**: every response carries a content security policy that allows only the app's own scripts, styles, images, fonts and connections, no inline script or style in HTML, no `eval`, no other site's content, and no framing of the pages, plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and a `Permissions-Policy` that turns off the camera, microphone, location, payment and USB. The pages must stay free of inline scripts, `style` attributes, style blocks and event handler attributes, and a test enforces it. The theme is applied by the file `static/theme.js`. HSTS is left to the reverse proxy.
- **First admin**: there is no default user or password. The first admin is created from the command line, which asks for the password: `python -m northstar.users create EMAIL NAME --admin`. The same tool resets passwords and is the way back in if every admin is locked out.
- **HTTPS**: the app serves plain HTTP and expects a reverse proxy to provide HTTPS. The documentation includes a Traefik example, with entrypoint and certificate resolver names as placeholders until confirmed, and says that plain HTTP is for trying the app out only.

## Release and distribution

Northstar is open source (MIT, copyright Declan Kenny) for other people to run themselves, so it must be secure by default, have defined releases and be easy to install and update.

- **Versions**: semantic versions. Before 1.0 anything may change, with notes. Database migrations, environment variables and the backup format always count as breaking and are always in the release notes.
- **Branches**: `main` is development. `release/X.Y` is cut when `vX.Y.0` is tagged, starting with `release/0.1`. A fix lands on `main` first and is backported, and each release is a tag `vX.Y.Z`. Only the latest minor version gets fixes until 1.0. Once the repo is public, rulesets protect `main`, `release/*` and `v*` tags: a pull request and passing checks are required, with no force-push or deletion.
- **Required before v0.1.0, not yet built**:
  - A loud startup warning when `NORTHSTAR_COOKIE_SECURE` is off.
  - A review of the password hashing cost.
  - Dependency and image scanning.
  - A `SECURITY.md` with supported versions, private reporting through GitHub, what to expect, and the threat model.
- **Images and updating (proposed, not yet confirmed)**: a public image `ghcr.io/declankenny/northstar` for amd64 and arm64, built by GitHub Actions when a `v*` tag is pushed, and tagged `X.Y.Z` (never reused), `X.Y` and `latest`. A user-facing `compose.yaml` that uses `image:` and has no `build:`, with the developer build in a separate file. Updating is `docker compose pull && docker compose up -d`. The app backs up the database before applying a pending migration and refuses to start on a database newer than itself, so a rollback is a restore of that backup. The image has a health check, and the project keeps a `CHANGELOG` and a README quick start.

## Acceptance for v0.1.0

- Accounts of every type can be created, and balances entered on arbitrary dates.
- Net worth on each date, and the month-end series built from it, match a hand calculation on a small synthetic dataset (automated test).
- Updating ten accounts takes one screen and one submit.
- Data survives a container restart, and a backup and restore has been tested.
- Tests use synthetic data only.
- Everything under "Required before v0.1.0" is built, the image is published, and an install and an upgrade have been rehearsed from the published image on a clean machine.

## Roadmap (not built)

Tracked as GitHub issues and milestones once the repo is public. In rough order:

1. **v0.2**: a first-run setup page that creates the first admin, with a React sign-in screen. The setup page is an unauthenticated route that grants admin, so it needs a guard such as a one-time token printed in the container log.
2. **OIDC sign-in** (for example Pocket ID): client settings from environment variables, users matched by verified email, optional admin and user groups, local sign-in switchable off. Needs a nullable password hash and a test against a fake provider.
3. **SimpleFIN daily balances pull.** What a real response taught us: every connected account returned a balance, including accounts with no positions or usable transactions. A balances-only request option skips transactions. The Bridge expects about 24 requests a day or fewer and can disable a token that exceeds that. The access URL is a credential and a setup token can be claimed once. Transactions come back for only about the last day unless a start date is passed, and positions came back for only some accounts.
4. Page state in the address (for example the date on the update screen).
5. More charts, such as the mix of assets by type, and a phone layout for balance entry.
6. Loan details such as rate and payment, CSV import and export, and retirement planning (not yet scoped). Transactions only if a real need appears.

## Open decisions

- TODO: how the roadmap is kept in git (issues, milestones, a project board).
- TODO: scheduled backups and the off-site copy, for the documentation and the example deployment.

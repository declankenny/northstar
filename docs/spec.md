# Northstar: v1 spec

Status: v1 complete (2026-10-30). Every acceptance item is met, including a restart of the container running in Docker Desktop on the development PC. It is not deployed to the deployment host. The next phase (a React frontend) has started, and its first page, the Dashboard, is built (see "After v1", item 6). Local login (accounts and sessions) is built (see "Authentication"). Items marked TODO or "Decision" are unresolved. Do not guess them.

Northstar is the app name. The repo is `github.com/declankenny/northstar` (private).

## Purpose

Track the household's financial position over time. v1 records dated balances for each account and shows net worth and per-account history. Entry is manual only.

## Scope

### In v1

- Accounts with a name, a class (Asset or Liability), and a user-configurable type.
- Dated balances per account, entered by hand.
- One screen to update balances for many accounts at once.
- Net worth (assets minus liabilities) over time.
- Per-account balance history as a table.
- Close an account to declutter the screens, without losing its history.

### Not in v1

- Transactions, opening balances, reconciliation.
- Investment positions or holdings.
- Budgets, categories, goals.
- Bank feeds. SimpleFIN is the first follow-up (see "After v1").
- Multiple currencies (decided for v1). Every amount is US dollars in integer cents, and no currency is stored in the database. A balance held in another currency, or in bitcoin or another crypto asset, is entered as its US dollar value at the time of the update. Quantities of units held are holdings, which are also not in v1. Supporting more currencies later means a currency on each account, a rate per balance and rounding rules. That is a separate design, and existing balances stay valid because they would default to USD.
- Loan schedules. A loan is just a liability with a balance history.
- Charts (decided). Net worth and balance history are shown as tables in v1. Charts wait for a modernized UI (see "After v1").
- A JSON API or a JavaScript frontend such as React. Pages are server-rendered (see "Technical shape"). Both are in scope for the next phase (see "After v1", item 6).

## Data model

Four tables for the household data. Two more, `users` and `sessions`, hold login (see "Authentication").

**account_classes**: id, name. Exactly two rows, Asset and Liability, loaded when the database is created. Not editable in the app.

**account_types**: id, name, class_id (refers to account_classes), stale_after_days (whole number of days, at least 1), created_at. The user can add, rename and delete types in the app. The starting list below is loaded when the database is created.

**accounts**: id, name, class_id (refers to account_classes), type_id, is_open (true or false, default true), notes (optional), created_at. The pair (type_id, class_id) must match a row in account_types, so an account's type always belongs to the account's class. The database enforces this with a composite foreign key (a link on two columns together), which also stops a type's class from changing while accounts use it.

**balances**: id, account_id, as_of_date, amount_cents (integer), note (optional), source ("manual" in v1; leaves room for a feed later), created_at, updated_at. One balance per account per date. Entering the same date again edits the existing balance.

### Account types (decided: user configurable)

Types are user configurable. There is no admin role in v1: anyone who can sign in can add, rename and delete types.

Starting list, loaded when the database is created:

Assets: checking, savings, brokerage, retirement, other investment, real estate, vehicle, other asset.
Liabilities: credit card, loan, mortgage, other liability.

Every type belongs to a class, Asset or Liability, chosen when the type is created. An account's class is what net worth uses. The type is a label within that class.

Class rules (decided):

- Each type has a class. Each account has a class and a type, and the type must belong to the account's class.
- **Editing an account's class is allowed at any time.** The save must also pick a type in the new class. Editing the class changes net worth for every past date the account covers, so the screen shows a confirmation that says how many past dates are affected. There is no audit trail in v1.
- A type's class cannot change while any account uses it.

Deletion rules:

- **Deleting an account (decided)** is allowed. It permanently deletes the account and all its balances, and net worth history changes to match. The screen asks for confirmation and states how many balances will be deleted. Closing is the way to hide an account and keep its history.
- **Deleting a type (decided)** is allowed only when no accounts use it. The Delete option is shown only for types with no accounts. To remove a type that is in use, the user first changes the type on each of its accounts (within the same class, or by editing the class as above), then deletes the type. The database backs this up with a restrict rule, so deleting a type that accounts still use is refused even if the screen is bypassed. Reason: deleting a type can never delete or silently change financial history.

### Rules (all decided)

- Amounts are integer cents, never floating point.
- **Dates and "today" (decided)**: balance dates are calendar dates with no timezone. The app has no timezone setting and no timezone logic in v1. "Today" is the date on the machine running the app, read in one `today()` function so tests can fix it. When deployed, the container's clock timezone is set with the standard `TZ` environment variable. Row timestamps such as created_at and updated_at are stored in UTC.
- **Balance dates and amounts (decided)**: a balance's date cannot be in the future, because in a manual tracker that is almost always a typo. Amounts are typed as dollars and cents, such as 1,234.56 or -25.00, and stored as integer cents. More than two decimal places is refused.
- **Sign convention (decided)**: each account has a class, Asset or Liability, and balances are stored as entered, the way a statement shows them. A mortgage of 250,000.00 is stored as 25000000 on a liability account. Net worth = sum of asset balances minus sum of liability balances. Balances may be negative on either side: an overdrawn checking account is a negative asset, and an overpaid credit card is a negative liability. Net worth needs no special cases for these. Reason: it matches how a balance sheet and a statement read, and it avoids sign mistakes when entering many balances at once.
- **Carry-forward (decided)**: net worth on date D uses each account's latest balance on or before D. An account with no balance on or before D contributes nothing. Two consequences are accepted. An account that is not updated keeps using its old balance, and the stale flag below is the safeguard. A new account contributes nothing before its first balance, so net worth steps on the day it first appears, unless an earlier-dated balance is entered.
- **Closing an account (decided)** only declutters the screens. A closed account (is_open false) drops off the Dashboard table and the Update balances screen, and stays visible on the Accounts screen under a "closed" filter with its full history. Net worth ignores is_open completely, because carry-forward does the work: a closed account's final balance is zero, and that zero carries forward.
  - An account can be closed only when its latest balance is zero or it has no balances. Otherwise the screen says to enter a final zero balance first. A final zero with a note covers an account that left the household.
  - Balances cannot be entered on a closed account until it is reopened. Reopening only sets is_open back to true.
  - The date an account closed is not stored. It is the date of the final zero balance.
- **Changing balances (decided)**: a balance can be added, edited or deleted from the account's detail page. Adding for a date that already has a balance replaces it. Editing may change the date, amount and note, and is refused if another balance on the same account already uses the new date. All three are refused on a closed account until it is reopened, so a closed account's final zero balance can't be removed or changed behind its back. The same date and amount rules as the Update balances screen apply. A note is optional text of at most 500 characters. The Update balances screen leaves existing notes alone.
- **Staleness (decided)**: each account shows days since its last balance, counted from the as_of_date of its latest balance to today. The account is flagged stale when that number is greater than its type's stale_after_days. An open account with no balances is also flagged, shown as "no balance yet". Closed accounts are not flagged. The threshold belongs to the type, so all accounts of a type share it. The check is one plain function, separate from the page code. A new type's form pre-fills 35, and the user can change it. A type that changes rarely, such as real estate, gets a large value instead of a special "never stale" setting.
  - Starting values (decided): 35 days for checking, savings, brokerage, retirement, other investment, other asset, credit card, loan, mortgage and other liability; 365 days for real estate and vehicle.

## Screens

1. **Dashboard**: the home page. Current net worth, total assets and total liabilities as of today, net worth over time as a table with one row for each month, newest first, showing assets, liabilities and net worth at the end of the month. Rows run from the first month with a balance through the current month. A month with no entries carries the previous values forward, and the current month is as of today and marked "to date". Entries made mid-month appear in that month's end value. Below it, a table of open accounts with latest balance, as-of date, and days since update.
2. **Update balances**: all open accounts in one table, one date field defaulting to today, one amount field per account. Blank rows are skipped, and a zero must be typed as 0. Each row also shows the account's last balance, its date, its age in days and the stale flag. Choosing another date reloads the page with that date's existing amounts filled in, and saving a date that already has a balance edits it. A save is all or nothing: if any amount is invalid, nothing is saved and each bad row says why.
3. **Account detail**: reached by clicking an account's name. A summary at the top (class, type, latest balance and its date, age and stale flag, number of balances and the earliest date, notes) with Edit, Close or Reopen, and Delete. Below it, the balance history table, newest first, with date, amount, note and source, and an Edit and a Delete link on each row. Above the table is a plain Add a balance form (date defaulting to today, amount, optional note). Deleting asks for confirmation on its own page. A modal for adding waits for the modern UI.
4. **Accounts**: add, edit (including class), close, reopen, delete.
5. **Account types**: add, rename and delete types, and set each type's stale_after_days. Each type's class is chosen when it is created. Each type shows how many accounts use it, and Delete appears only when that count is zero.

## Technical shape

Stack, architecture, packaging, authentication and backup are decided. Deployment is still a proposal.

- **Stack (decided)**: Python, FastAPI, server-rendered HTML templates, and SQLite. No charting library, no React and no frontend build step in v1.
- **Architecture (decided)**: business logic lives in plain Python functions, separate from the page routes and templates. This covers the net worth calculation, the close rules and staleness. Routes call these functions and templates only display the results. Reason: a React frontend could be added later by putting JSON endpoints over the same functions. v1 has no JSON API. The next phase adds read-only endpoints under `/api` (see "After v1", item 6).
- **Packaging (decided)**: one docker container and one SQLite file on a mounted volume. Reason: household scale, fewest moving parts, simple backup.
- **Backup (decided)**: never copy a live SQLite file by hand while the app runs. A command line tool does it with SQLite's online backup: `python -m northstar.backup create FILE` and `python -m northstar.backup restore FILE [--replace]`. The database is `NORTHSTAR_DB` (default `data/northstar.db`).
  - A backup is written to a temporary file, checked (SQLite integrity check, foreign keys, the expected tables) and only then renamed into place. It never overwrites an existing file, and a failure leaves no partial file.
  - A restore checks the backup first and needs the app stopped. It refuses to replace an existing database unless `--replace` is given, and then it moves the old file aside as `<name>.before-restore-<time>` instead of deleting it. Leftover journal files are moved aside too, so an old journal can't corrupt the restored file.
  - The tool reports only counts, never names or amounts. A backup file holds the real financial data, so it stays out of the repository (`backups/` and backup file names are ignored) and in a private place.
  - There is no backup page in the web app, so there is no new way to read the data over the network.
  - TODO scheduling backups and the off-site copy, aligned with the deployment host's snapshot setup. That belongs to deployment.
- **Authentication (decided)**: local accounts. Every page, the `/app` bundle and every `/api` endpoint need a signed-in user. Only `/login` and its stylesheet are public. Pages redirect to `/login`, and `/api` answers 401.
  - **Users**: a `users` table (email, display name, password hash, `is_admin`, `theme`). `is_admin` is stored and returned by `current_user()`, but nothing is gated on it yet. Every signed-in user sees all household data, so there is no per-user data. There is no user management page.
  - **Passwords**: scrypt from Python's standard library (no new dependency), minimum 12 characters, no other composition rules. A wrong password and an unknown email give the same message and take about the same time. There is no lockout or rate limit yet (see `docs/backlog.md`).
  - **Sessions**: a random token in an `HttpOnly`, `SameSite=Lax` cookie, valid for 30 days from login (not extended on use). The `sessions` table stores only the token's SHA-256, so signing out or changing a password really ends the session on the server. The cookie is marked `Secure` when `NORTHSTAR_COOKIE_SECURE=1`, which must be set when the app is served over HTTPS.
  - **Profile (decided)**: every signed-in user has a Profile page in the React UI at `/app/#/profile`, reached from their name in the navigation (and the header of the classic pages). They can change their display name (1 to 100 characters), change their password (the current password is required, this browser stays signed in and their other browsers are signed out) and choose Light or Dark. The email and `is_admin` cannot be changed there. The theme is stored on the user (`users.theme`, default dark), so it follows them between browsers. The browser also keeps a copy, because the sign-in page and the first paint run before the account is known, and the account's value replaces it once the app loads. The endpoints are `GET` and `PATCH /api/me` and `POST /api/me/password`, and they only ever touch the signed-in user. Pages are chosen by the part of the address after the `#`, so there is no router library.
  - **Where it lives**: one middleware (`require_login`) enforces access and `auth_routes.current_user()` is the one function routes use to ask who is signed in.
  - **First user and user management (decided)**: there is no default user and no password in the image or compose file. Users are created from the command line, which asks for the password at a prompt: `python -m northstar.users create EMAIL NAME [--admin]`, `set-password EMAIL` and `list`. In Docker: `docker compose exec northstar python -m northstar.users create ...`. Reason: nothing to ship or leak, and no open signup route. A first-run setup page waits (see `docs/backlog.md`).
  - **Backups** now contain password hashes and sessions. They stay private, as before.
  - **OIDC (for example Pocket ID) is not in this phase.** It is in `docs/backlog.md`.
  - **Deployment gate**: unchanged in spirit. Login is now in the app, but deployment to the deployment host still needs HTTPS (so `Secure` cookies) and Declan's approval. TODO choose how it is exposed (reverse proxy and network) when deployment starts.
- **Deployment**: a stack in `the deployment repo` through its PR workflow. Out of scope until v1 runs locally.

## Acceptance for v1

- Accounts of every type can be created, and balances entered on arbitrary dates.
- The net worth on each date, and the month-end series built from it, match a hand calculation on a small synthetic dataset (automated test). There is one calculation, net worth on a date, and the series only chooses which dates to ask about.
- Updating ten accounts takes one screen and one submit.
- Data survives a container restart. One backup and restore has been tested.
- Tests use synthetic data only.

## After v1 (not committed)

1. **SimpleFIN daily balances pull.** What we learned from a real response:
   - Every connected account returned a balance, including accounts with no positions and no usable transactions.
   - SimpleFIN offers a balances-only request option that skips transaction data.
   - The Bridge expects roughly 24 requests per day or fewer and can disable a token that exceeds that.
   - The access URL is a credential. A setup token can be claimed only once.
   - The setup token's claim host was `beta-bridge.simplefin.org`.
   - Transactions come back for only about the last day unless a start date is passed.
   - Positions came back for only some accounts.
2. Loan details such as rate and payment.
3. CSV import and export.
4. Transactions, only if a real need appears.
5. Retirement planning. A future goal, not yet scoped.
6. **Modern UI and charts (next phase, active).** A React frontend, with charts for net worth and balance history, over JSON endpoints on the existing logic functions.
   - **Stack (decided)**: React, TypeScript and Vite, built to a static bundle that FastAPI serves from the same container and the same origin, so there is no CORS setup. The source is in `frontend/`. The build goes to `northstar/web/spa` (not committed) and is served at `/app`. The old server-rendered pages stay in place until the new UI matches them. Reason: it has the most documentation, and it can be served without a second container. Each frontend dependency needs a stated reason. Today they are React and react-dom (the framework), and Vite, its React plugin, TypeScript and Vitest for building, type checking and testing the date and money code. All versions are pinned exactly.
   - **Charts (decided for now)**: no chart library. The net worth chart is drawn as SVG, because it is one simple area. Revisit when a second kind of chart is needed.
   - **Series API (decided)**: a series is `net_worth_on` asked about regularly spaced dates, and the server works out every number, so no rule lives in the frontend. `GET /api/networth?start=&end=&period=` takes a period of `day`, `week` or `month` (default `month`).
     - `end` defaults to today and cannot be after it. `start` defaults to the date of the first balance and is never earlier than that, because before any balance net worth is zero only because nothing was entered, and a chart would show a false climb from zero. The response reports the dates actually used, and the server's `today`.
     - The dates asked about are `start`, then steps of the period, ending exactly on `end`. Weeks count back from `end`. Months are calendar month ends, the last cut off at `end`.
     - One request is limited to 1,000 points, otherwise it is refused with a 422. A bad date, period or range is also a 422.
     - A balance entered mid-period shows at the next sample, so a chart is up to one period late except at its newest point, which is exact.
     - The balance history chart on the account detail page will use the same endpoint with an optional `account_id`. It limits the same `net_worth_on` calculation to that one account, so there is no second calculation. The account's balance lands in `assets` or `liabilities` by its class, as in the totals. `start` then defaults to that account's own first balance, and an unknown account is a 404. Not built yet.
   - **First step, a sliver (built)**: that endpoint and a React Dashboard at `/app/`. Each range button is a request: 1M and 3M use days, 6M, YTD and 1Y weeks, and 5Y and ALL months. The page learns the server's `today` from a first request with no dates, then asks for the chosen range. The endpoint is tested against the hand-calculated dataset, and every daily point is checked against an independent plain-Python calculation. The month-end table on the classic Dashboard is unchanged. The Docker build has a Node stage that produces the bundle.
   - **Read-only first**: endpoints are `GET` only, apart from the signed-in user's own profile (see "Authentication"). Login now exists, so endpoints that change data are no longer blocked on it, but each one still needs its own design. They need the same cross-site POST check as the pages.
   - **Dates** stay as `YYYY-MM-DD` strings in JSON and in the frontend. The frontend never creates a JavaScript `Date` (it counts whole days instead), so the no-timezone rule holds. The frontend tests run in a US timezone to prove it. Money stays integer cents, shown with whole-number arithmetic. The frontend contains no net worth rules: it chooses a start and a period, and draws what comes back.
   - **Dashboard in the new UI (decided)**:
     - Layout: a labeled left navigation (Dashboard, Update balances, Accounts, and an **Admin** group holding Account types), three tiles (net worth, assets, liabilities) above one large chart. The page fits the window with no scrolling. Account types is under Admin.
     - Each tile shows its change over the chosen range. A falling liability is shown as good news.
     - Chart: an area of the series, no axis (an overview; analysis pages come later), with a tooltip of the nearest sample's date and the three totals. The range buttons (1M, 3M, 6M, YTD, 1Y, 5Y, ALL) sit above the chart. A tile's change is the last point of the series minus the first, so it is exactly the server's numbers. A range never starts before the first balance.
     - The open-accounts table is not on this Dashboard. It belongs on the Accounts page.
     - Style: steel blue accent, clean sans-serif with tabular numbers, system fonts (nothing is loaded from outside), a Light and Dark choice on the Profile page (dark by default, stored on the user, see "Authentication").
     - Balance entry is designed for a desktop browser only. There is no phone layout yet.
   - Not yet in the new UI: Update balances, Accounts and Account detail, Account types. The navigation links to the server-rendered pages for these. Which moves next is TODO.
   - Deployment is still out of scope until Declan approves.

## Open decisions

Resolved: app name and repo (Northstar, `github.com/declankenny/northstar`), stack and database (see "Technical shape"), sign convention for liabilities (positive amount plus a class, see "Rules"), account types (user configurable, with a fixed Asset/Liability class table), editable account class, deletable accounts and types, carry-forward, closing accounts, authentication (local accounts, see "Technical shape"), currency (USD only in v1), stale threshold (per account type, with starting values), no timezone awareness in v1.

All v1 decisions in this list are settled. New questions that come up while building get added here.

Resolved for the next phase: frontend stack (React, TypeScript and Vite), no chart library for now, and the Dashboard design (see "After v1", item 6).

Open for the next phase:

- Which screen moves to the new UI next, and which further charts to build (for example per-account history, and the mix of assets by type). TODO.
- Deployment gate: HTTPS and how the app is exposed on the deployment host. TODO. (Login itself is decided, see "Authentication".)

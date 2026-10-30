# Northstar: v1 spec (DRAFT)

Status: draft for Declan's approval. Items marked TODO or "Decision" are unresolved. Do not guess them.

Northstar is the app name. The repo is `github.com/declankenny/northstar` (private).

## Purpose

Track the household's financial position over time. v1 records dated balances for each account and shows net worth and per-account history. Entry is manual only.

## Scope

### In v1

- Accounts with a name, a class (Asset or Liability), and a user-configurable type.
- Dated balances per account, entered by hand.
- One screen to update balances for many accounts at once.
- Net worth (assets minus liabilities) over time.
- Per-account balance history as a table and a chart.
- Archive an account without losing its history.

### Not in v1

- Transactions, opening balances, reconciliation.
- Investment positions or holdings.
- Budgets, categories, goals.
- Bank feeds. SimpleFIN is the first follow-up (see "After v1").
- Multiple currencies. USD only. TODO confirm no other currency is needed.
- Loan schedules. A loan is just a liability with a balance history.
- A JSON API or a JavaScript frontend such as React. Pages are server-rendered (see "Technical shape").

## Data model

Four tables.

**account_classes**: id, name. Exactly two rows, Asset and Liability, loaded when the database is created. Not editable in the app.

**account_types**: id, name, class_id (refers to account_classes), created_at. The user can add, rename and delete types in the app. The starting list below is loaded when the database is created.

**accounts**: id, name, class_id (refers to account_classes), type_id, archived_at (nullable date), notes (optional), created_at. The pair (type_id, class_id) must match a row in account_types, so an account's type always belongs to the account's class. The database enforces this with a composite foreign key (a link on two columns together), which also stops a type's class from changing while accounts use it.

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

- **Deleting an account (decided)** is allowed. It permanently deletes the account and all its balances, and net worth history changes to match. The screen asks for confirmation and states how many balances will be deleted. Archive is the way to hide an account and keep its history.
- **Deleting a type (decided)** is allowed only when no accounts use it. The Delete option is shown only for types with no accounts. To remove a type that is in use, the user first changes the type on each of its accounts (within the same class, or by editing the class as above), then deletes the type. The database backs this up with a restrict rule, so deleting a type that accounts still use is refused even if the screen is bypassed. Reason: deleting a type can never delete or silently change financial history.

### Rules (Decision: confirm each, except where marked decided)

- Amounts are integer cents, never floating point.
- **Sign convention (decided)**: each account has a class, Asset or Liability, and balances are stored as entered, the way a statement shows them. A mortgage of 250,000.00 is stored as 25000000 on a liability account. Net worth = sum of asset balances minus sum of liability balances. Balances may be negative on either side: an overdrawn checking account is a negative asset, and an overpaid credit card is a negative liability. Net worth needs no special cases for these. Reason: it matches how a balance sheet and a statement read, and it avoids sign mistakes when entering many balances at once.
- Net worth on date D uses each account's latest balance on or before D. An account with no balance on or before D contributes nothing.
- An archived account counts toward net worth for dates before its archived_at date and not after. Its history is kept.
- Each account shows days since its last balance. Flag it as stale past a threshold. TODO choose the default threshold.

## Screens

1. **Dashboard**: current net worth, total assets, total liabilities, net worth over time, and a table of accounts with latest balance, as-of date, and days since update.
2. **Update balances**: all active accounts in one table, one date field defaulting to today, one amount field per account. Blank rows are skipped.
3. **Account detail**: balance history chart and table. Add, edit, delete a balance.
4. **Accounts**: add, edit (including class), archive, restore, delete.
5. **Account types**: add, rename and delete types. Each type's class is chosen when it is created. Each type shows how many accounts use it, and Delete appears only when that count is zero.

## Technical shape

Stack and architecture are decided. Packaging, backup, authentication and deployment are still proposals.

- **Stack (decided)**: Python, FastAPI, server-rendered HTML templates, SQLite, and a small charting library. No React and no frontend build step in v1.
- **Architecture (decided)**: business logic lives in plain Python functions, separate from the page routes and templates. This covers the net worth calculation, the archive rules and staleness. Routes call these functions and templates only display the results. Reason: a React frontend could be added later by putting JSON endpoints over the same functions. Do not build a JSON API in v1.
- **Packaging (proposed)**: one docker container and one SQLite file on a mounted volume. Reason: household scale, fewest moving parts, simple backup.
- **Backup (proposed)**: do not copy a live SQLite file while the app runs, because recent writes can sit in the write-ahead log files. Use SQLite's online backup or stop the container first. TODO align with the deployment host's snapshot and off-site backup setup.
- **Authentication (proposed)**: sign in through the existing Pocket ID (OIDC) or the existing reverse proxy setup. TODO confirm how other the deployment host stacks handle this.
- **Deployment**: a stack in `the deployment repo` through its PR workflow. Out of scope until v1 runs locally.

## Acceptance for v1

- Accounts of every type can be created, and balances entered on arbitrary dates.
- The net worth series matches a hand calculation on a small synthetic dataset (automated test).
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

## Open decisions

Resolved: app name and repo (Northstar, `github.com/declankenny/northstar`), stack and database (see "Technical shape"), sign convention for liabilities (positive amount plus a class, see "Rules"), account types (user configurable, with a fixed Asset/Liability class table), editable account class, deletable accounts and types.

1. Net worth carry-forward and archive rules above.
2. Authentication.
3. Currency. TODO
4. Default stale threshold. TODO
5. Application timezone for "today". TODO

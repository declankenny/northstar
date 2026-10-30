# Northstar: v1 spec (DRAFT)

Status: draft for Declan's approval. Items marked TODO or "Decision" are unresolved. Do not guess them.

Northstar is the app name. The repo is `github.com/declankenny/northstar` (private).

## Purpose

Track the household's financial position over time. v1 records dated balances for each account and shows net worth and per-account history. Entry is manual only.

## Scope

### In v1

- Accounts with a name, a type, and an asset or liability side.
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

Two tables.

**accounts**: id, name, type, side (asset or liability), archived_at (nullable date), notes (optional), created_at.

**balances**: id, account_id, as_of_date, amount_cents (integer), note (optional), source ("manual" in v1; leaves room for a feed later), created_at, updated_at. One balance per account per date. Entering the same date again edits the existing balance.

### Account types (Decision: confirm this list)

Assets: checking, savings, brokerage, retirement, other investment, real estate, vehicle, other asset.
Liabilities: credit card, loan, mortgage, other liability.

Type sets the side by default. The side is stored explicitly so an unusual account can override it.

### Rules (Decision: confirm each)

- Amounts are integer cents, never floating point. A liability is entered as the positive amount owed. Net worth subtracts it.
- Net worth on date D uses each account's latest balance on or before D. An account with no balance on or before D contributes nothing.
- An archived account counts toward net worth for dates before its archived_at date and not after. Its history is kept.
- Each account shows days since its last balance. Flag it as stale past a threshold. TODO choose the default threshold.

## Screens

1. **Dashboard**: current net worth, total assets, total liabilities, net worth over time, and a table of accounts with latest balance, as-of date, and days since update.
2. **Update balances**: all active accounts in one table, one date field defaulting to today, one amount field per account. Blank rows are skipped.
3. **Account detail**: balance history chart and table. Add, edit, delete a balance.
4. **Accounts**: add, edit, archive, restore.

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

Resolved: app name and repo (Northstar, `github.com/declankenny/northstar`), stack and database (see "Technical shape").

1. Account type list.
2. Net worth carry-forward and archive rules above.
3. Authentication.
4. Currency. TODO
5. Default stale threshold. TODO
6. Application timezone for "today". TODO

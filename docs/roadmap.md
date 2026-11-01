# Northstar roadmap

This file is Northstar's position paper: where it is going, the principles that shape every release, and why the releases come in the order they do. It changes rarely, and a change to it is an argument made in a pull request.

The plan itself lives in GitHub, not here:

- **Milestones** (`v0.2`, `v0.3`, …) are the releases. A milestone holds what is actually in that release.
- **Issues** hold the scope, using three labels:
  - `epic`: a release's functional theme, assigned to its milestone. Its body is the definitive scope, open decisions and completion criteria for that theme.
  - `feature`: planned work. A feature is usually a sub-issue of an epic, created when its milestone is planned in detail rather than all up front. Supporting work that stands alone, such as OIDC sign-in, is a `feature` in its milestone with no epic.
  - `enhancement`: a request someone filed through the feature-request template, not yet triaged. Triage either turns it into an `epic` or `feature`, or closes it as not planned.
- **The backlog** is `epic` and `feature` issues with no milestone: things Northstar might do that are not yet scheduled. Scheduling one means giving it a milestone.

`spec.md` describes what is built. A feature moves into the spec in the pull request that builds it.

## Product direction

Grow Northstar from a manual household net-worth tracker into a household finance application that connects current financial position, spending and long-term planning, and that households outside the United States can adopt.

The balance-based model stays the foundation. Transaction detail explains financial movement, but complete transaction records are never a prerequisite for tracking net worth.

## Foundations

These hold across every release.

- **Balances are authoritative.** Net worth is calculated from recorded balances, not reconstructed from transactions.
- **Statement balances are reconciliation checkpoints.** Transactions explain the movement between statement checkpoints. Ordinary balance snapshots can still be recorded between statements.
- **A reconciliation difference stays visible.** Northstar never silently inserts a balancing transaction or changes a statement balance to force agreement. Any accepted adjustment is explicit and explained.
- **Accounts can stay balance-only.** Property and other valuations never require a transaction ledger.
- **Automation is an input source.** Manual entry, CSV and SimpleFIN feed the same underlying records. A successful sync does not mean an account is reconciled.
- **Balance movement is not investment performance.** Reports describe changes in balances. Without cash-flow and holdings information they do not claim returns.
- **Projections are not records.** Planning features show their assumptions and never present a projection as a recorded fact.
- **In-app recovery complements backups.** Undo and history make mistakes recoverable; they never replace database backups.

## What 1.0 means

Before 1.0, any minor release may break things, with notes. 1.0 marks the point where **the balance-based product is complete and dependable, and another household can adopt it without the author's help.**

From 1.0, Northstar makes a compatibility promise rather than freezing its schema. A release is breaking only if it breaks this promise:

- Existing data survives every supported upgrade, with its meaning unchanged.
- Balance-only accounts keep working as they do today.
- Northstar CSV files exported by any release from 1.0 on can be imported by that release and every later one. An older release is not required to read a newer release's export.
- Configuration changes come with a documented migration path.
- A backup taken by any release from 1.0 on can be recovered by restoring it with the release that took it, then upgrading. Restoring an old backup directly with a newer release is not part of the promise.

Internal tables can change in a minor release as long as the promise holds. That is what lets transactions, SimpleFIN and budgeting arrive as 1.x minor releases.

Two things have to be settled before 1.0 because they shape the promise:

- **Multi-currency.** It changes what a stored amount means for every account. Adding it before 1.0 means the promise is made about the model households will actually use, rather than about one that every installation would have to migrate away from.
- **The relationship between balance observations and statement checkpoints.** Statements are built in 1.1, but whether a checkpoint is its own record, which record drives net worth when the two disagree on a date, and what correcting one means are decided before the data model is promised.

## Order of releases

| Release | Theme |
| --- | --- |
| v0.2 | Balance CSV import and export |
| v0.3 | Multi-currency and locale-aware formatting |
| v0.4 | Household reporting |
| v0.5 | Data history and recovery |
| **v1.0** | Stabilization |
| v1.1 | Transactions, transaction CSV and statement reconciliation |
| v1.2 | SimpleFIN automation |
| v1.3 | Budgeting |
| Independent | Retirement and FIRE planning |

The milestones say what each release contains. This order is the position:

- **CSV import comes first.** It is what makes Northstar useful to anyone with existing history, and every later report is only as good as the data behind it. Northstar's own CSV format is canonical and independent of locale, so an export imports identically anywhere. Someone else's spreadsheet is a separate case, read through an explicit column mapping and an explicitly chosen date and number interpretation.
- **Multi-currency comes before reporting.** Reporting is then built once, already able to separate exchange-rate effects from real balance movement.
- **Locale formatting ships with multi-currency.** It does not change the data model, but a household outside the United States needs both to adopt Northstar, so they arrive together.
- **Data history builds on CSV import.** Batch undo needs a record of each change (previous value, source, batch). Full history grows that record rather than building it twice.
- **Transactions come before SimpleFIN.** A feed needs somewhere to put transactions, duplicate handling and reconciliation before it can be trusted.
- **Budgeting comes last.** It depends on categorized transactions with known coverage.
- **Retirement planning is independent.** It uses recorded assets and explicit assumptions, so it can start at any time.

## Every release

These are requirements of each release, not milestones of their own:

- **Every epic has completion criteria.** "Done when" is written before the work starts.
- **Schema changes are tested for recovery.** Any release that changes the schema tests backup, restore and upgrade from the previous release.
- **Provenance is recorded from v0.2 on.** Each recorded change says who made it, when, which operation produced it and what it replaced. Which changes are recorded is decided in v0.2. Records that exist before v0.2 become a migration baseline with no earlier history. History screens can come later, but information that was never recorded cannot be reconstructed.
- **Unrelated work stays out of epics.** A feature that ships in the same milestone but serves a different purpose is a standalone `feature`, not a completion requirement for the epic.
- **Fixes land on `main` first** and are backported to the release branch, as the spec requires.

## Not planned

Investment holdings, tax reporting and bill payment are not planned. Each would need a concrete use case and its own design. The releases above are already a substantial expansion.

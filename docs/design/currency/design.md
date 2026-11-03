# Multi-currency and locale-aware formatting: design

Status: a draft dated November 3, 2026. It has been checked against `docs/spec.md`, `docs/roadmap.md` and #56 but not against the code, and the open questions are listed at the end. Nothing here is the spec or the decisions log.

Each item below is labelled. **Decided** means Declan agreed it. **Proposed** means it is the recommendation and has not been challenged or confirmed. **Open** means it is unresolved: do not guess it.

## Outcome

A household whose accounts are all in one non-USD currency can use Northstar, and so can a household with accounts in several traditional currencies. Each account keeps its balances in its own currency. Net worth is calculated in one permanent system currency. Users type and read numbers and dates in their own locale. Locale never decides an account's currency or how a file must be read.

Northstar stays a balance-based tracker. Useful historical context matters more than the last digit of an old exchange rate.

## Currencies

**Catalog** (decided). A `currencies` table holds the ISO 4217 code, name and minor-unit precision, supplied by Northstar and read-only to admins. Admins control whether a currency is enabled for new accounts and how its rates are collected. Which catalog entries are suitable (withdrawn codes, special non-currency codes) is open. A catalog entry can exist without an automatic rate source.

**System currency** (decided). Chosen once, before the first account exists, and never changed. An existing installation is migrated to USD. A fresh installation chooses it on the first-run setup page. Another household currency means a fresh instance and an export and import, which must carry actual amounts and not relabel dollars.

**Single and multi-currency** (proposed). There is no switch. An installation is single-currency while the system currency is the only row in `currencies`, and the interface then hides currency choices and rate screens. Adding a second currency makes it multi-currency, permanently, because currency rows are never deleted. The server needs no separate enforcement: an account's currency must be an enabled currency, and only the system currency is enabled at first. The Add Currency wizard shows the irreversibility warning. The System Properties design may still add an explicit toggle for clarity.

**Account currency** (decided). Set when the account is created and never edited. A wrong choice on an account with no balances is fixed by deleting and recreating it, since a deleted account frees its name. Creating an account needs an enabled currency and, for a foreign currency, at least one stored rate. This does not promise coverage for every older date.

**Availability and collection** (decided). Disabling a currency stops new accounts using it and keeps everything existing. Rate collection continues while any open, live account uses the currency, whether or not it is enabled. Closed accounts end in a zero balance and need no new rates.

## Rates

**Direction** (decided). One stored rate means 1 unit of the foreign currency = X units of the system currency. No separate reference currency. A system-currency row is unnecessary. Positive, finite decimals only. A provider adapter asks for the system currency as the quote, so no inversion is needed (to verify, see Provider).

**Identity** (decided). A rate is identified by currency and actual observation date, unique together. The exact shape of the table is open and gets locked down when it is designed.

**Selection** (decided). On reporting date D, each account uses its latest balance on or before D, then the latest stored rate on or before D. Balance carry-forward and rate carry-forward are separate. Today's spec rules for accounts with no balance by D are unchanged.

**Zero balances** (proposed). A zero converts to zero without looking up a rate. This lets a closed account stop collection, avoids a stale-rate warning for a currency that contributes nothing, and means a zero recorded before a currency's rates begin does not make that date unavailable. A missing account still contributes nothing, as today.

**Insert-only feeds and corrections** (decided). An automatic fetch inserts missing observations and never overwrites a stored rate for the same currency and date, whether that rate came from a provider or from an admin. An admin can correct a rate's value but cannot delete a rate or change its date. A correction can change historical totals and the screen says so. Provenance is a source column (provider or manual) and the change log records corrections. A separate "corrected" marker is not planned.

**History** (decided). Daily rates only. When an admin adds a currency, the wizard asks for the date rates should start from, defaulting to the provider's earliest date for that currency, and fetches daily rates from there. Dates before it are unsupported for that currency. The wizard can be rerun to start earlier. There is no monthly sampling, cutoff or per-currency override. TODO: confirm the volume and the provider's range limits before relying on this.

## Valuation

**Exact money** (decided). Native amounts are integers in the currency's minor unit. Input with more decimals than the currency allows is refused, never rounded. No floating point anywhere.

**Conversion** (decided). For native integer N, native precision p, reporting precision q and exact decimal rate R, the result is `round_half_away_from_zero(N × R × 10^q / 10^p)`. Each account is converted and rounded on its own and the converted integers are summed. The asset-minus-liability sign convention is unchanged.

**Where it runs** (proposed). The server computes every number. Conversion is exact decimal arithmetic in Python. If the conversion sits behind a database view, the view finds each account's balance and rate for a date and Python multiplies and rounds, because SQLite has no decimal type and a 10^13 amount times a scaled rate overflows 64-bit integers. The rate is stored as text and parsed as a decimal. This is open until the table and view are designed.

**Limits** (proposed). Keep the current ceiling of about 10^13 in minor units, which stays inside JavaScript's safe integer range for any system currency.

**Missing coverage** (open). A requested result must never present a partial total as complete or silently omit an unconverted account. Because rates carry forward, missing coverage can only fall before a currency's earliest stored rate, so the affected dates are always a prefix. Two designs fit: hide a requested graph entirely when any point lacks coverage, or start the series at the first covered date with an explanation, like the existing rule that a series never starts before the first balance. The choice waits for the conversion view design. Stale rates beyond the threshold (default 14 days, from System Properties) warn and still calculate.

**Calculated on demand** (decided). Converted balances are never stored as authoritative. Any later cache must be invalidated by balance changes, rate changes and account changes.

## Locale

**Per-user locale** (decided). Saved on the user, with a system default copied to new users when they are created. Changing the system default does not change existing users. The migration default for existing users is US English (proposed, since it preserves behaviour). Interface text stays English.

**What locale controls** (decided). How numbers and dates are shown and typed. Stored dates stay `YYYY-MM-DD` and stored amounts stay integers.

**Entry** (proposed). One shared server-side parser turns a typed amount in the user's locale into minor units, used by every route that takes money. The frontend assists but does not decide validity. The currency's precision is a natural safeguard: in a locale where `,` is the decimal mark, `1,234` for a two-decimal currency has three decimals and is refused, not read as 1,234. Currencies with three decimals need extra care. Test vectors per supported locale, not heuristics.

**Dates** (open). Showing a date in a locale's order collides with the frontend rule that it never creates a JavaScript `Date`. The options are a small formatter that reorders the `YYYY-MM-DD` string by numeric pattern, or one tested UTC-pinned exception. Leaning toward the formatter, with a short list of patterns. Entry stays on the native date input, which always yields an ISO value. Record the choice in `decisions.md` with the code. The supported locale list is open.

**Symbols and codes** (open). Whether amounts show a code or symbol, and how to separate `$` for USD and CAD.

## CSV

**Export** (decided). The Northstar CSV stays canonical and independent of locale: `YYYY-MM-DD` and a plain decimal amount, now in the account's currency and precision. Whether to add a Currency column is open. It would be informational because the importer does not read it.

**Import** (decided). Import trusts that the file is in the account's currency. There is no Currency column mapping and no currency-symbol block, so the spec's current handling of a mapped Currency column is removed when this ships. The review says "all balances are treated as" followed by the chosen account's currency, as it says dollars today. Number-style detection must use the account's precision: `1.234` is only thousands for a currency with no minor unit, and is ambiguous for one with three decimals, so the person chooses. A file in another currency imported into the wrong account is a user error that Northstar does not try to detect.

## Provider and collection

**Provider** (proposed). [Frankfurter](https://frankfurter.dev/). Checked on November 3, 2026: a public API (`/v2/rates`, with `base`, `quotes`, `date`, `from` and `to`) with rates from central banks, free of keys and quotas but rate limited, history going back to 1948 for some currencies, per-currency coverage available at `/v2/currencies`, and open source. TODO: it does not state a time of day for publication, a maximum range size, or attribution terms; check these and the license page before building, and confirm `base` and `quotes` give the foreign-to-system direction directly.

**Daily run** (proposed). There is no scheduler in Northstar. A command, `python -m northstar.rates fetch`, run from the operator's cron like the nightly backup, fetches from the day after the newest stored rate for each collected currency up to today. A missed run fixes itself on the next one and no job table or stored last-run value is needed. The run time lives in the crontab and is documented in `docs/operating.md`. An admin Fetch now button runs the same code. Background writes are authored by the system user. A manual fetch is authored by the admin who pressed the button.

**Safety** (decided). Fetch outside write transactions and commit validated batches through the shared writer. A partial failure keeps committed rates and a rerun is safe. A provider failure never stops balance entry. Requests carry only currencies and dates.

## Add Currency wizard

Steps (proposed): choose a catalog currency and see the permanent system currency; choose automatic or manual-only; choose the date rates start from, with provider coverage shown; fetch with progress and failures; review stored coverage and enable the currency. Manual-only lets an admin enter dated rates. It needs a mockup before any build. What happens after a partly successful fetch, and how a manual-only currency's coverage is reviewed, are open.

## Migration and recovery

An existing installation gets the catalog and no change to any amount. Its system currency is USD, and USD is on every account, if it has at least one account; otherwise the system currency is unset and an admin sets it on the System Properties screen before an account can be created. Users get the default locale. The money columns keep the name `amount_cents` and now hold integers in the account currency's minor unit (decided, see the implementation plan). Test upgrade from v0.2, a backup before the upgrade, and restore after it. Update `docs/schema.md`, the audited-field registry and the operator guide with the code.

## Validation

The acceptance list from the interview carries over: existing USD results unchanged; system currency fixed once set; accounts always have a valid enabled currency; native amount entry enforces precision; direction, exact conversion, per-account rounding, halfway cases of both signs, zero, liabilities and differing precisions; no future rate used for an earlier date; fetch never overwrites; corrections change valuation and not the balance; date edits and deletes refused; stale rates warn; locale defaults affect new users only; locale does not change how a CSV is read; backup, restore and upgrade preserve currency settings, rates and balances. Hand-calculated fixtures on synthetic data and rendered checks, not tests that mirror the implementation.

## Open questions

- Missing-coverage presentation (truncated series or hidden graph).
- Rate table shape and precision, and whether conversion sits behind a view.
- The date formatter, the supported locales and symbols versus codes.
- Whether the export gains a Currency column.
- Catalog policy for withdrawn and special codes, and for precision changes.
- Provider terms, publication time and range limits.
- Wizard behaviour after a partial fetch, and manual-only coverage review.
- Whether the System Properties design adds a multi-currency toggle.
- Whether zero balances need no rate (proposed above, not yet confirmed).

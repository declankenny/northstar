# Locale: design

Status: the agreed design for #126 (the locale core) and #127 (the places a locale is chosen), dated November 5, 2026. It is part of the v0.3 multi-currency work described in [currency/design.md](currency/design.md), but is its own design because locale is not only about currency. Nothing here is built. It is not the spec or the decisions log, which change only with the code. Everything is agreed unless marked **TODO**, which means unverified or unresolved: do not guess it.

## Outcome

Each person reads and types numbers and dates in their own conventions, such as `1.234,56` and `07.05.2026`. Locale controls only how numbers and dates are shown and typed. It never decides an account's currency or how a CSV file is read, and the interface text stays English. Storage does not change: amounts stay integers in the currency's minor unit and dates stay `YYYY-MM-DD`.

#126 builds the core: the catalog, the saved preference, the parser and the formatter. #127 builds the controls and the interpreted-amount preview. They are two stacked pull requests that ship together, so acceptance testing never needs a database edit.

Out of scope: the importer and exporter (#128), the number style offered on a spreadsheet import (#129), the Northstar CSV, translated interface text, other numbering systems, lakh grouping and time zones.

## Principles

- **The conventions are data we own.** They come from CLDR, the Unicode standard for locale data, with the Northstar rules below. The design supports CLDR-derived conventions, not all of CLDR's formatting.
- **The runtime does not use the browser's `Intl`.** Browsers carry different CLDR versions and write some marks differently, and the server has to read exactly what the page shows. For example, Node's `Intl` writes the Swiss group mark as `'` (U+0027) where CLDR has `’` (U+2019). One table read by both sides cannot disagree.
- **The server is authoritative.** The frontend repeats the parsing rules so a change can show as it is typed, and the server checks every amount when it is saved.

## The catalog: `ref_locales`

A reference table in the existing `ref_` convention: loaded by migrations, never written at run time, no audit columns, not logged, and refused by the writer. It is the only runtime source of locale conventions, and it is the list a person chooses from.

| Column | Constraints | Purpose |
| --- | --- | --- |
| `tag` | `TEXT PRIMARY KEY NOT NULL` | The BCP 47 tag, such as `en-US`. |
| `label` | `TEXT NOT NULL`, not empty | The English label shown in a selection, such as `English (United States)`. |
| `decimal_mark` | `TEXT NOT NULL`, one character | The decimal separator. |
| `group_mark` | `TEXT NOT NULL`, one character, different from `decimal_mark` | The canonical group separator, with its exact Unicode character. |
| `date_template` | `TEXT NOT NULL` | A Northstar template, such as `{month_short} {day}, {year}`. |
| `currency_position` | `TEXT NOT NULL CHECK (currency_position IN ('prefix', 'suffix'))` | Where the currency identifier goes. |
| `currency_code_spacing` | `TEXT NOT NULL` | The exact text between an alphabetic currency code and the number. |
| `cldr_version` | `TEXT NOT NULL` | The CLDR version the row was generated from. |

The tag is the primary key, unlike the integer ids of the other `ref_` tables, because it is already the identifier in preferences and the API. Shipped tags are stable and never removed.

**The date template** uses a small vocabulary: `{year}`, `{month}`, `{month2}`, `{month_short}`, `{day}` and `{day2}`, plus literal text. Month names are English, like the rest of the interface. The application never interprets a raw CLDR pattern.

**Three conventions are application rules, not columns:** groups of three digits, grouping from four digits, and an ASCII minus `-`. They are documented in the spec and tested once. A column is added when a locale needs it.

### The six locales

| Locale | Decimal | Group | Date template | Currency |
| --- | --- | --- | --- | --- |
| `en-US` | `.` | `,` | `{month_short} {day}, {year}` | prefix |
| `en-GB` | `.` | `,` | `{day} {month_short} {year}` | prefix |
| `de-DE` | `,` | `.` | `{day2}.{month2}.{year}` | suffix |
| `fr-FR` | `,` | U+202F (narrow no-break space) | `{day} {month_short} {year}` | suffix |
| `de-CH` | `.` | `’` (U+2019) | `{day2}.{month2}.{year}` | prefix |
| `ja-JP` | `.` | `,` | `{year}/{month2}/{day2}` | prefix |

7 May 2026 and 1,234,567.50 in each, with English month names:

| Locale | Date | Amount |
| --- | --- | --- |
| `en-US` | May 7, 2026 | 1,234,567.50 |
| `en-GB` | 7 May 2026 | 1,234,567.50 |
| `de-DE` | 07.05.2026 | 1.234.567,50 |
| `fr-FR` | 7 May 2026 | 1 234 567,50 |
| `de-CH` | 07.05.2026 | 1’234’567.50 |
| `ja-JP` | 2026/05/07 | 1,234,567.50 |

`en-US` is today's display exactly. TODO: the exact `currency_code_spacing` of each row comes from CLDR's currency spacing data and is not yet verified. The generator writes it and a person checks it in review.

### Adding a locale

A new locale is not only a row. The generator refuses a locale whose conventions go beyond the application rules (a group size other than three, grouping from more than four digits, a minus other than `-`, a date pattern outside the template vocabulary), instead of fitting it into the model. A person checks the result, and the locale must also be on a hand-checked allowlist. Babel does not expose CLDR's minimum-grouping-digits rule, so the generator also probes Node's `Intl` for each candidate to see its group size and four-digit rule.

## The generator

A developer tool in `scripts/`, run by a person. It reads CLDR through Babel, translates it into the columns above and writes a migration.

1. Run the pinned tool.
2. Review the migration, in particular the exact Unicode characters and any Northstar override.
3. Commit and ship it. The application applies it through the normal migration process.
4. At run time only `ref_locales` is read. Nothing at run time reads CLDR.

- **Babel** is pinned in the `dev` extra only (2.18.0, CLDR 47) and is not in the production image. TODO: it is tested on Python 3.14.7, not on 3.15, which the image uses.
- **Odd characters** are written as `char(8239)`, `char(8217)` and so on, each with a comment naming the Unicode character, so the migration is reviewable.
- **Later updates** are new migrations. A released migration is never edited.
- **CI** installs Babel and fails if the committed rows differ from the generator's output. It never skips the check.
- **Licence:** CLDR data is distributed under the Unicode licence. TODO: confirm what notice it requires, and where it goes.

## The preference

`users.locale` is `TEXT NOT NULL DEFAULT 'en-US' REFERENCES ref_locales (tag)`.

- Existing users get `en-US`, which keeps today's behaviour. New and reactivated users get the value of `ui.locale.default`, written explicitly. The schema default is only a fallback.
- SQLite refuses to add a `REFERENCES` column with a non-null default while foreign keys are enforced. The migration therefore uses the `-- northstar: rebuild` mode, which turns enforcement off and checks the foreign keys and the database before commit. It seeds `ref_locales`, including `en-US`, first. Tests check that existing users hold a valid tag, that an unsupported tag is rejected afterwards, and that enforcement is on again.
- It is not logged: `('users', 'locale', 0)` in `sys_audited_fields`, like the theme.
- A tag is validated twice on purpose, by the foreign key in the database and in application code for a clear message. No `CHECK` holds the supported list. A locale row that a user references cannot be removed.

## The default: `ui.locale.default`

A String system property, seeded `en-US`, not nullable, editable by an admin. Hint: "Number and date format for new or reactivated users. Changing this does not change other users' saved preferences."

- A validator `catalog_locale` is registered in `VALIDATORS` and linked in `ref_property_validators` at position 1. After the generic checks it requires an exact match against `ref_locales.tag` through a parameterised query, refuses anything else with a clear message, and accepts without locking, so the default can change later.
- There are no `ref_property_lookups` rows. `ref_locales` is the single source of supported tags and labels, so adding a locale needs no duplicate property data.
- The System properties page receives the catalog with its response and offers the locales as a search box, as it does for the system currency, so the value is never free text.
- Using a String property and a foreign key on `users.locale` is intentional: one lives in a generic property table and the other in a dedicated column, so they are enforced by different mechanisms.
- A reactivated user takes the current default, as the theme does. Active users are never changed by a new default.
- There are no properties for separators, templates or currency placement. Those are application conventions.

## The parser

One function extends `money.parse_amount` and takes the user's locale. Every route that takes money uses it, with the signed-in user's locale and the account's currency. The command line, which has no user, uses `en-US`. The importer's own reader (`csvparse`) is not changed.

**The promise:** it interprets input using the selected locale and never guesses another one. It does not promise to refuse everything ambiguous: `1.234` means grouped 1234 under `de-DE`, because that is what the locale says.

- Only ASCII digits are read.
- **The decimal mark** is the locale's, and only that. The other common mark is refused with a message naming the right one.
- **Group marks** are optional and must be well formed: one to three digits, then groups of exactly three, and none after the decimal mark.
- **Look-alike marks** are normalised only for the matching group mark: space, no-break space and U+202F for a space group, and `'`, `’` and `ʼ` for an apostrophe group. This small table is keyed by the canonical mark, not by locale. Arbitrary whitespace is never removed and apostrophes are never replaced globally. This is stricter than today, where every space is dropped, so `1 2` is now refused. The changelog says so.
- **More decimal places than the currency has** is refused, never rounded. For a three-decimal currency the locale decides the reading.
- A leading `$` is accepted only for US dollars. A leading `-` is the minus.
- The maximum, 9,999,999,999,999 minor units, is unchanged.
- The frontend's `parseCents` follows the same rules, because it drives the live totals on screen.

## Formatting

Three separate contracts:

- **Display:** grouping and the currency identifier, such as `1.234,56 EUR`.
- **Editable input:** the locale's decimal mark, no grouping and no currency, such as `1234,56`. It round-trips exactly through the parser.
- **Canonical export:** unchanged, locale-independent decimal text.

Display does not round-trip, because it includes a currency code that the parser does not accept.

- **Amounts** are grouped from four digits using the locale's marks, in the currency's own digits, with the currency placed by `currency_position` and spaced by `currency_code_spacing`. The symbol `$` is shown only for US dollars in `en-US`, with no space. Every other case shows the currency code.
- **Negative amounts** put the minus at the very start. CLDR's `de-CH` puts it after the code (`CHF-1’234.50`); the design uses one rule.
- **Counts**, such as "1,234 balances", use the locale's group mark in the same way.
- The preference is labelled "Number and date format", so it does not suggest a translated interface.

### Dates

A small function fills the date template from the `YYYY-MM-DD` text. The frontend never creates a JavaScript `Date`, so the no-timezone rule holds. `Intl.DateTimeFormat` could do this only on a `Date` pinned to UTC, whose text varies by browser and version and would put a French month name in an English screen. The native date input keeps showing the browser's own order, with an ISO value, and cannot follow the Northstar locale. A decisions entry records this with the code.

## Loading the user's locale

`/api/me` returns the selected tag and the formatting fields from `ref_locales`: the decimal and group marks, the date template, the currency position and the spacing.

- The authenticated shell waits for `/api/me` and shows a retry if it fails. The sign-in page stays outside it and reachable. Money forms never start under an assumed locale, and nothing is prefilled in one locale and later reread under another. This also removes the brief wrong currency symbol before the currency loads.
- If `/api/me` is unavailable, the pages wait for the retry and do not fall back to default formatting.
- `ui.locale.default` supplies a preference when a user is created. It does not stand in for a saved preference while the page loads.

## Locale changes while a form is open

A money form sends the locale tag it was initialised under. The server compares it with the saved preference in the same transaction as the balance write. On a mismatch it writes nothing, the page keeps the draft and says what changed, and nothing is retried under the new locale. This includes a preference changed in another tab. It is built with #127, where a locale can first change.

## Screens (#127)

- **Profile:** a "Number and date format" dropdown in the existing Appearance panel, under the theme. Its options are the `label` of each `ref_locales` row. Like the theme, it saves as soon as it is chosen, with no Save button and no hint text.
- **New-user form (admin):** the same dropdown, starting from the system default.
- **Interpreted amount:** a line under an amount box that appears once something is typed and reads "Reads as 1.234,56 EUR", or gives the refusal, such as "Use , for decimals." It uses the shared parsing rules and the account's currency. It is on single balance entry (add and edit) and on every row of the Update balances screen, where each row reads in its own account's currency, so a yen row refuses decimals. A bulk save is still all or nothing.
- **A save after the format changed elsewhere:** the form shows "Your number and date format changed to X. Nothing was saved." The typed amount stays in the box.

## Tests

- **Shared vectors.** One file of vectors per supported locale, read by pytest and vitest. The expected results are written by hand, independently of the generator, so the tests do not copy a generator mistake. A drift test checks that the conventions in the file equal the migrated `ref_locales` rows, because vitest cannot read the database.
- **Parser:** both decimal marks, grouped and ungrouped, the look-alike marks, malformed grouping, signs, 0, 2 and 3 decimals, the maximum, and the other locale's marks refused.
- **Formatter:** dates for every locale, amounts in 0, 2 and 3 decimals with currency spacing, negatives and counts. Editable text round-trips exactly, and display has its own independent expected outputs.
- **Preference and default:** existing users keep `en-US`; a new user takes the default; a changed default leaves others unchanged; reactivation follows the rule above. The property and the preference both accept supported tags and reject others, changing the default does not lock it, and adding a catalog entry needs no duplicate property data.
- **Database:** the foreign key exists and rejects an unsupported tag independently of the application, and enforcement is restored after the migration.
- **Forms:** they wait for the locale, do not reinterpret a draft when the preference changes, and refuse a save made under a different locale. The preview uses the account's currency on every row.
- **Packaging:** the migrations ship, and neither Babel nor the generator is in the image or needed at run time.
- **Upgrade from v0.2 on a copy of a database,** a backup before it, and a restore, as for #125.

## Documents with the code

The spec (the user's locale, the parser and the formatting), a decisions entry for the table, the generator and the date approach, `docs/schema.md`, the changelog (Breaking: a migration, and the stricter handling of spaces), `docs/operating.md` if the default is mentioned, a licence notice for CLDR, and a note on running the generator in `CONTRIBUTING.md`.

## TODO

The Unicode licence notice, the verified currency spacing values, Babel on Python 3.15, and recheck Safari's support for `Temporal` if the date approach is ever revisited.

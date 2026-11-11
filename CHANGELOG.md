# Changelog

All notable changes to Northstar are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and the project follows [Semantic Versioning](https://semver.org/). Before 1.0 anything may change between minor versions.

Each released version has a **Breaking** heading that says what an upgrade means for the database (migrations), the environment variables and the backup format. Those three always count as breaking before 1.0. If it says "Nothing", an upgrade needs no action beyond pulling the new image.

## [0.5.0] - TODO release date

Lists you can shape (#120). Balances, Accounts, Currencies (admins) and an account's own balance history are lists that share one set of controls: search, filters (that you can save, privately or for everyone), sorting by any column, grouping, columns you choose and put in the order you like, paging, and Export CSV of what you see. The Balances list shows every balance across all accounts and opens each one on a page of its own, where it is edited or deleted. The Accounts page is now this kind of list, so it no longer has the Assets and Liabilities totals, the Open and Closed buttons or the row menu (the Dashboard has the totals, and closed accounts are a filter). An upgrade applies nine database changes, with a checked backup first, and needs no change to your settings. See "Upgrading from 0.4 to 0.5" in the operator guide.

### Added

- An account's balance history is a list of the framework (#224): newest first, twelve to a page, with the date, the balance and its change from the balance before it. You can sort it by a column and page it. The date opens the balance's page, which is where a balance is edited or deleted, so the Edit and Delete buttons are gone from the account page. It has no search, filters, grouping, column choice or export (the account's own Export CSV is unchanged).
- The Currencies page is a list of the framework (admins only): search the catalog, filter it (and save a filter), sort it by any column, group it, choose its columns and their order, and export it to CSV, like Balances and Accounts. It has the same columns as before (Code, Name, Decimal places, Enabled, Accounts), 100 to a page. A currency's code, not its name, opens its page. The All, In use and Enabled buttons are the filters Enabled is Yes and Accounts is at least 1, and a search finds a currency by any part of its code or name.
- The Accounts page is a list of the framework (#190): search it, filter it (and save a filter, private or for everyone), sort it by any column, group it, choose its columns and their order, and export it to CSV, like Balances. It opens on the shared filter "Open accounts", with Account, Type › Class, Type, Currency, Last balance, Reporting value, Balance date, Balance age (days), Stale and Balances. An account's name opens its page, which has every action; the menu on each row, the Open and Closed buttons, the totals and the Stale badge are gone (closed accounts are the filter Open is No, and the Dashboard has the totals). Adding an account refreshes the list in place, keeping its sort, filters and page.
- The balance page's form has no empty line between the amount and the note (#214): how a changed amount was read now shows beside its label.
- Links are easier to see (#212). A link in a table cell or a title is the accent colour, no longer the bold text colour, and is underlined when the mouse is over it. A link inside a sentence is the accent colour with a soft underline that firms up on hover.
- Export CSV in the lists (#189). A button in a list's footer, to the right of Previous and Next with how many rows it will have, downloads what the list shows as a CSV file: every matching row, in the list's order, with your columns, however many pages that is. It is UTF-8 with a byte-order mark so a spreadsheet shows accents, dates are `YYYY-MM-DD`, amounts are plain decimals with no symbol, and text that starts like a formula is made plain text with an apostrophe. An empty result gives the headers alone.
- Group by in the lists (#188). A column's menu has Group by, which gathers the rows under a header with the group's name and the number of rows. A group that goes on to the next page repeats its header marked continued, with how many of its rows are on that page. A header collapses its group, and Expand all and Collapse all in the grouped column's menu do it for every group, on other pages too. Sorting by the grouped column reverses the groups. The grouping is in the address; amounts cannot be grouped, and a timestamp is grouped by its date.
- A page for each balance (#210), opened from its date in the Balances list: its amount and note are edited, with Save, and it is deleted, with the same confirmation and conflict messages as the account page. It shows the balance's currency, its value in the system currency with the date of the rate used, and who entered and last changed it. The date is not changed there. A closed account's balance can be read but not changed. Leaving with unsaved changes asks first.
- More ways to filter a choice column, such as an account's type (#206): is, is not, is one of (the old "is any of", relabelled), is not one of, is empty and is not empty. "Is not" and "is not one of" include rows that have no value. "Is not empty" is also offered beside "is empty" on number, date and amount columns, and on a Yes/No column that can be empty. A filter saved before the change keeps working.
- In the lists (#208): a table with many columns scrolls sideways and no longer overlaps its text, a column of a related table is headed by where it comes from ("Account › Updated by"), a long text is cut with an ellipsis and shown in full on hover, and "+ Add column" stays open so several columns can be added in a row.
- A Balances page (#203): every balance across all accounts in one list, newest first, with each balance's account, type, value and currency and its value in the system currency. Search it, filter it (and save a filter, private or for everyone), sort it by any column, and choose its columns and their order. Its Account links to the account, and its Currency to the currency page for admins. Editing and deleting a balance from the list, grouping and export come next.

### Changed

- The internal API (#228): an account's page no longer carries its balances (they are the list `account_balances`), the net worth series of an account says how many of its balances are inside its dates, `GET /api/balances/{id}` answers with the balance and a few facts about its account instead of the account's whole page, and `GET /api/balances/{id}/neighbours` is new. Nothing changes on any screen: the Delete confirmation says the same, asking for what it needs when Delete… is pressed.
- The internal API: `GET /api/currencies` (the old catalog list) is gone, the list is `POST /api/lists/currencies`; a currency's own endpoints are unchanged.
- The internal API: `GET /api/accounts` (the old list, with its totals) is gone, the list is `POST /api/lists/accounts`; `GET /api/accounts/options` gives what the Add account dialog offers, and `POST /api/accounts` answers with the new account's id. The API is not a stable contract.
- The Accounts and Update balances pages and closing an account now read an account's last balance from a view, `last_balances`, instead of each working it out in its own query (#190). Nothing changes on any screen.
- An account's class is now read from its type and is no longer stored on the account (#181). Nothing changes on any screen, and the rule that a type's class cannot change while an account uses it is kept, by a trigger.

### Breaking

- Migration: `0019_account_class_from_type` rebuilds `accounts` without `class_id` and `account_types` without its `UNIQUE (id, class_id)`, recreates the views over them, adds the trigger `account_types_class_fixed_while_used` and keeps both tables' id counters. A checked backup is made first.
- Migration: `0020_live_balance_values` adds a view of each live balance with its value in the system currency, for the list framework. It calls a SQL function that the application registers on every connection it opens, so the view can only be read through the application: opening the database file in the `sqlite3` shell cannot read that one view, while backups and checks are unaffected.
- Migration: `0021_user_list_prefs` adds the table that holds a person's page size for each list, for the list framework. A checked backup is made first.
- Migration: `0022_list_filters` adds the table that holds saved filters for the lists, for the list framework. A checked backup is made first.
- Migration: `0023_user_list_columns` rebuilds `user_list_prefs` so that a person can save the columns they chose for a list, and so that its page size may be empty. Every saved page size is kept. A checked backup is made first.
- Migration: `0024_account_summaries` adds two views, `last_balances` (each account's newest balance) and `account_summaries` (the figures of each account: its balance count, last balance and date, value in the system currency, age and whether it is stale), for the Accounts list. The second works out the age with a SQL function that the application registers on every connection it opens, so, like `live_balance_values`, it can only be read through the application. No data changes. A checked backup is made first.
- Migration: `0025_accounts_list` replaces the view `account_summaries` with one that also has the account's own columns, so that the list framework can follow an account's relations, and adds the shared default filter "Open accounts" for the Accounts list. No data changes. A checked backup is made first.
- Migration: `0026_currency_summaries` adds a view of the currencies with how many accounts use each, for the Currencies list. It reads the accounts, so it can only be created after them and no data changes. A checked backup is made first.
- Migration: `0027_account_balances` adds a view of each balance with its change from the account's balance before it, for the account page's history. It reads the balances, so it can only be created after them and no data changes. A checked backup is made first.
- Environment variables: nothing.
- Backup format: nothing. A backup taken before the upgrade restores under the old version and upgrades again.

## [0.4.0] - 2026-11-09

Sign-in through one OpenID Connect identity provider, such as Authentik or Pocket ID (#67). It is off until an admin sets it up, and password sign-in keeps working beside it unless an admin switches it off. A person is linked to their Northstar user by the provider's verified email, new users are created only when an admin allows it, and an OIDC user has no password. The operator guide has a section on setting it up, including what linking by email trusts the provider with. It was set up and tried on a real Pocket ID instance (linking, creating, the refusal when creation is off, and switching password sign-in off and back on from the host). Authentik was not tried.
### Added

- The settings of OIDC sign-in (#166), under System properties: `oidc.enabled`, `oidc.provider`, `oidc.issuer`, `oidc.client_id`, `oidc.user.allow_creation`, `oidc.session.lifetime_hours` and `system.auth.local.enabled`. They refuse a configuration that could leave nobody able to sign in.
- Storage and rules for sign-in through an identity provider (#167): a table that binds a person to a user by the provider's issuer and subject (never deleted or changed, and kept when the user is deleted), the rules for who an identity is (a verified email links an existing user, a new user is made only when allowed, a deleted user never comes back), sessions that record how they started and, for OIDC, last for the configured hours, and users with no password.
- Password sign-in is switched off only once an admin has signed in through OIDC, which is now checked against the stored bindings.
- Sign-in through an OpenID Connect provider (#168): `GET /api/auth/oidc/login` and `/api/auth/oidc/callback`, using the authorization code flow with PKCE, a state, a nonce and a browser binding. Every failure returns to `/login?oidc_error=CODE` with a fixed code. Starts and returns are limited per address. A session made by OIDC ends at its next request if the issuer or client ID has changed.
- Password sign-in refuses with 403 when `system.auth.local.enabled` is off.
- The sign-in page offers "Continue with" the provider when OIDC is on, above the password form, and the button alone when password sign-in is off. It words each failure that comes back from the provider, and never shows text from the provider (#169).
- `GET /api/auth/methods`, a public answer to which ways of signing in are on and the name for the provider's button. It carries no issuer, client ID or secret.
- Users has a Sign-in column (Local, OIDC, or Local and OIDC). The reset-password dialog says when someone has no password today, and the Profile of someone who signs in only through the provider explains that instead of showing a form that could not succeed.
- A Boolean kind of system property, shown as a Yes or No dropdown.
- `NORTHSTAR_PUBLIC_URL`, `NORTHSTAR_OIDC_CLIENT_SECRET_FILE` and `NORTHSTAR_OIDC_CLIENT_SECRET`, all optional. Setting both forms of the secret stops Northstar starting.
- `python -m northstar.signin enable-local`, which turns password sign-in back on from the host, with no provider and no session.

- A section of the operator guide on signing in through an identity provider, and an upgrade note for 0.4 (#170).
- The OIDC design notes under `docs/design/oidc/` now describe what was built.

### Dependencies

- `joserfc` and `cryptography` (runtime), for checking the provider's tokens and keys. The decisions log says why not Authlib.

### Security

- The image upgrades `zlib1g` to Debian's patched version (CVE-2026-76844, CVE-2026-85091) until the base image is rebuilt with it.

### Breaking

- Migration: `0017_oidc_settings` adds the Boolean data type and the seven system properties above, with defaults that change nothing (password sign-in on, OIDC off). A checked backup is made first.
- Environment variables: `NORTHSTAR_PUBLIC_URL`, `NORTHSTAR_OIDC_CLIENT_SECRET_FILE` and `NORTHSTAR_OIDC_CLIENT_SECRET` are new and optional. An installation that sets none of them is unaffected.
- Migration: `0018_oidc_identities` adds the `user_identities` table, the `sys_login_transactions` table, the session columns `auth_method` and `config_fingerprint` (every existing session becomes a local one and keeps its expiry), and the operation kind `oidc`. A checked backup is made first.
- Backup format: nothing.

## [0.3.0] - 2026-11-07

Multi-currency and locale-aware formatting. Every account has a currency, household totals are converted into one system currency with exchange rates that Northstar fetches daily from Frankfurter (or that an admin enters), and each person chooses their number and date format. A new installation is set up on a first-run page, with a one-time token from the container log, in place of the `users create` command.

### Added

- A first-run setup page (#64). A new installation prints a one-time setup token in the container log and has no user until the person opens `/setup`, pastes the token and fills in one form: the administrator's name, email and password, the household reporting currency (required, with none preselected, and locked once saved), the default number and date format, and the time zone. The administrator and those settings are saved together or not at all, and then the person signs in normally. Setup is available only while no administrator exists, deleted ones included. The token stops working when setup is finished or the app restarts (a restart prints a new one), a setup session lasts 30 minutes, and wrong tokens are throttled. Run `docker compose logs northstar` to find the token. An installation that already has an administrator has no setup page and no token.
- Exchange rates fetched for you (#131). Once a day, at the time in the system property `currency.rate.fetch_time` (18:00 in your time zone until you change it), Northstar fetches the rates of every foreign currency that is enabled or has an open account from Frankfurter, which publishes central-bank rates, and adds the days that have none, from each currency's rates start. It never changes a rate that is already stored, so a rate you typed or corrected stays. A currency's page says when it runs and how the last run went, and labels fetched rates Frankfurter. `docker compose exec northstar python -m northstar.rates fetch` fetches now. A currency the provider does not list is skipped, so enter its rates by hand.
- The in-app scheduler (#138): the machinery for jobs that run once a day at a time an admin sets, with no job yet (the exchange-rate fetch, #131, is the first). A new Time kind of system property is `HH:MM` on a 24-hour clock, read in the installation's time zone and edited with a time box. The scheduler keeps a lock for each job, so a job whose lock has run out cannot save anything, records every run, makes up a missed time once after a restart, and stops promptly with the server.
- The installation's time zone (#152). A new system property, `system.timezone`, under Admin, System properties, holds a zone name such as `America/Chicago` and decides what "today" is. It starts empty, and the first time Northstar starts with it empty it saves `TZ` into it, so an existing installation keeps its zone. After that `TZ` is ignored and the log warns if it differs. An empty property with no `TZ` means UTC. Changing the zone moves where "today" begins by at most a day and changes no stored date.
- Accounts in other currencies (#149). The Add account dialog has a Currency box when a currency other than the system currency can be used (enabled, with at least one stored rate), and the API takes an optional currency code. The Accounts list and the Update balances screen have a Currency column, and every balance, amount box, reading line and conflict message is in the account's own currency. An account's page has a Currency tile. Totals stay in the system currency. No migration.
- Exchange rates and conversion into the system currency (#130). Each currency has a page, opened from its name on the Currencies list, where an admin switches it on or off (saved at once, with the date its rates start from) and adds or corrects dated rates, with a warning when the newest rate is stale. Household net worth converts each account with the latest rate on or before the date, rounded half away from zero, and a chart that cannot reach back to the first balance because a currency has no rate before a date starts later and says why. A single account stays in its own currency. The system currency is always enabled, a new account in another currency needs a stored rate, and system properties gain a Date type, `currency.rate.stale_days` and `currency.rate.start.default`.
- Balance imports now use the account currency and its decimal places (#128). An inline number-style picker resolves ambiguous amounts, with a preview before review. Currency columns are ignored, but the review notes it, without blocking, when a file says another currency than the account's. Excess precision is refused without rounding, and the review names the destination currency.
- System properties (#124): an admin page, System properties under Admin in the sidebar, for settings that belong to the whole installation. Properties are listed by group on the left and edited one at a time on the right, with a hint beside each name, Save and Revert on a changed value, and the reason shown when a value is refused. Every change is in the change log. The first properties are `ui.theme.default`, which sets the theme every new user starts with (whether added from the page, the command line or by reactivating a deleted user), `system.balance.stale_days`, which sets the stale-after days the Add type form starts at, and `system.currency`, which becomes the system currency with the currency catalog.
- A currency for every account (#125). The ISO 4217 catalog of 155 currencies is built in, every account has a currency that is set when it is created and never changes, and the installation has one system currency, set on the System properties page with a search box over the catalog (by code or name). It is chosen once before the first account and locked as soon as it is saved. An upgraded installation with any account is set to US dollars and locked. One with none starts unset, and the Add account dialog says to set the currency first (the server refuses too). Amounts are entered and shown in the currency's own digits (whole yen, three places for dinars), and an export writes an account's own digits. Accounts in different currencies, exchange rates and locale formatting come later in 0.3.
- A Currencies page for admins (#141), under Admin in the sidebar: the currency catalog as a searchable list with each currency's code, name, decimal places, whether it is enabled and how many accounts use it, and filters for all, in use and enabled. It is read-only.
- Choosing a number and date format (#127). A "Number and date format" dropdown in the Appearance panel of the profile, saved as soon as it is chosen, and the same choice on the admin's form for adding a user, which starts at the default. Under every amount box a line now says how what you typed reads ("Reads as 1.234,56 EUR") or why it cannot be read. If your format is changed in another window while you have a form open, saving is refused, nothing is saved and what you typed is kept and read in the new format. The Update balances boxes show the currency code in place of a dollar sign for any currency but US dollars in US English.
- Messages the server writes now say dates and numbers in your format too: "There is already a balance on 01.09.2026", the dates in an import that cannot be undone, the duplicate dates in an import file, and counts of a thousand or more. Counts on the screens (the number of balances, days since the last one) are grouped by your format, and the Imports page shows its dates in it.
- A number and date format for each person (#126). Amounts and dates are shown and typed in the person's own conventions, such as `1.234,56` and `07.05.2026`. Six formats are supported to start with: US and UK English, German (Germany and Switzerland), French and Japanese. Existing users keep the US English display they had. A new user takes the default format, which an admin sets on the System properties page. The format is chosen from the profile screen (#127).
- The page now waits for your account's details before it shows anything signed in, and offers to try again if they cannot be loaded.

### Changed

- Typed amounts no longer ignore every space: a space is accepted only as the group mark of a locale that uses one (such as French), so `1 2` is refused where it used to read as 12. Currency codes are separated from the number by a no-break space.
- A third-party notices file, `THIRD_PARTY_NOTICES.md`, carries the Unicode CLDR licence for the locale data, and the image includes it, with the licence, under `/licenses/`.
- The image's base, `python:3.15-slim`, is moved to a newer build whose `apt` is 3.0.4, which fixes CVE-2026-109518 (HIGH) that the image scan reported in 3.0.3. Nothing else in the image changes.
- The Add type form starts a new account type at the `system.balance.stale_days` system property, 35 days until an admin changes it, where the 35 was fixed in the form. Existing types keep their own days, and any number of at least 1 can still be typed.
- The sidebar and the sign-in page show the new brand mark in place of the plain star (#76), as a pair of images that follows the theme you chose in Northstar, not the operating system's: a white road on a blue tile on the light theme, and a blue road on a white tile on the dark one. The browser tab icon is unchanged.
- The sign-in page is now a page of the React app (#65), and the app's files under `/assets/` are public so it can load. Signing in and signing out go through `/api/auth/login` and `/api/auth/logout`, which answer JSON, and the page goes on with a full page load. The look, the throttling, the cookie and the content security policy are unchanged. Signing in now needs JavaScript, as the rest of the app already did.
- Two dependencies are gone: `jinja2`, which only rendered the old sign-in page, and `python-multipart`, which only read its form.

### Breaking

- `python -m northstar.users create` is removed. The first admin is now made on the setup page, and later users on the Users page. `set-password` and `list` stay. An installation that already has an administrator is unaffected. No migration, no new environment variable and no change to the backup format.
- Migration: `0016_rate_fetch` adds the system property `currency.rate.fetch_time` (18:00) and the operation kind `scheduled`. A checked backup is made first. **From the first scheduled time, Northstar calls `api.frankfurter.dev` over HTTPS once a day**, sending only currency codes and dates. Clear `currency.rate.fetch_time` to switch it off. No amount changes, and no new environment variables or change to the backup format.
- Migration: `0015_scheduler` adds the Time data type for system properties and two tables, `sys_jobs` and `sys_job_runs`. A checked backup is made first. No setting is added and no job is registered yet, so nothing runs. No amount changes, and no new environment variables or change to the backup format. Backups are still the host's job, and the operator guide's script is unchanged.
- Migration: `0014_system_timezone` adds the system property `system.timezone`. A checked backup is made first. `TZ` now only sets the first-start value of that property, and changing `TZ` later has no effect. No amount changes, and no new environment variables or change to the backup format.
- Migrations: `0012_rename_stale_days_property` renames the system property `balance.stale` to `system.balance.stale_days`, and `0013_exchange_rates` adds the `exchange_rates` table, a `rates_start` column on currencies, the view `account_days`, a Date data type for system properties and the properties `currency.rate.stale_days` and `currency.rate.start.default`, and enables the system currency. A checked backup is made first. No amount changes, and no new environment variables or change to the backup format. Anything that rebuilds `accounts` or `balances` must now drop and create `account_days` as well.
- Migrations: `0011_locales` adds the `ref_locales` table and a `locale` column on users, and a new system property `ui.locale.default`. A checked backup is made first. No new environment variables and no change to the backup format.
- Migrations: `0010_currencies` adds the `currencies` table and rebuilds `accounts` to add `currency_id`, and `system.currency` is now checked against the catalog. A checked backup is made first. No amount changes: the money column keeps its name and now holds the minor unit of the account's currency, which is cents for every existing account. No new environment variables and no change to the backup format. A fresh installation, or an upgraded one with no accounts, must set the system currency on the System properties page before adding the first account.
- Migrations: four new tables hold the system properties, and the first three properties are added. A checked backup is made first. Nothing else changes for an existing installation, and there are no new environment variables and no change to the backup format.

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

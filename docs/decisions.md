# Northstar: decisions

Why Northstar works the way it does. `spec.md` says what the rules are. This file says why, and what was rejected, so nobody has to rediscover it.

Entries are appended and never rewritten. To change a decision, add a new entry that says it replaces the old one. Dates start on 2026-10-31. Earlier decisions were made while v1 was built and have no recorded date.

Each entry: the decision, the reasons, and what would make us revisit it.

---

## Money and dates

### Money is integer cents, in US dollars only
Floating point cannot hold money exactly, and a rounding surprise in a financial total destroys trust in every number. Amounts are typed as dollars and cents and stored as integer cents. No currency is stored. A balance in another currency or in crypto is entered as its dollar value at the time. Revisit if multiple currencies are really needed: that means a currency per account, a rate per balance and rounding rules, with existing balances defaulting to USD.

### Dates are calendar dates with no timezone
A balance is "as of" a day, not an instant. Adding timezone handling would add bugs and no value for a household tracker. "Today" is the machine's date, read in one `today()` function so tests can fix it, and a deployment sets `TZ`. The frontend never creates a JavaScript `Date` (it counts whole days), because `new Date("2026-10-30")` is read as UTC midnight and shows as Oct 29 in the US. Revisit if one household needs two timezones, which is unlikely.

### Balances are stored as entered, with the class saying what they mean
A mortgage of 250,000.00 is stored as 25000000 on a liability account, the way the statement shows it. This matches how a statement and a balance sheet read, and it avoids sign mistakes when many balances are entered at once. Negative balances are allowed on either side, so net worth needs no special cases. Rejected: storing liabilities as negative numbers.

## Net worth

### One calculation, `net_worth_on`, with carry-forward
Net worth on a date uses each account's latest balance on or before it. Everything else (month-end series, charts, totals) only chooses which dates to ask about, so there is a single place to be wrong and a single place to test against a hand calculation. The accepted cost is that an account nobody updates keeps its old balance, so the stale flag is the safeguard, and a new account makes net worth step on the day it first appears.

### The frontend holds no net worth rules
The server computes every number the screens show, and the frontend only chooses dates and draws the answer. For the same reason the Update balances page shows each row's change as plain subtraction but no net worth preview: a preview would be a net worth rule in the frontend. Revisit by adding a server endpoint if a preview is ever wanted.

## Accounts and types

### Account types are configurable inside a fixed two-class model
Households have different accounts, so types are editable, but every type belongs to Asset or Liability, because the class is what net worth uses. Stale limits belong to the type, so all accounts of a type share a limit, and a type that rarely changes (real estate) gets a large number, not a special "never stale" setting. Admins alone manage types, while everyone can use them.

### Editing an account's class is allowed and rewrites history
People mis-classify accounts. The edit must pick a type in the new class and tells the person how many balances and from when it affects. There is no audit trail. Rejected: forbidding class changes, which forces delete and re-enter. Revisit if the lack of an audit trail causes real trouble.

### Deleting an account is allowed, deleting a type only when unused
Deleting an account removes its balances and says how many. Closing is the way to hide an account and keep history. A type can only be deleted when no account uses it, and the database enforces that with a restrict rule, so deleting a type can never change financial history.

### Closing only declutters, and needs a final zero balance
Net worth ignores whether an account is open. Closing requires the latest balance to be zero (or no balances), so carry-forward does the work and no special case is needed. The close date is not stored: it is the date of the final zero. Rejected: a closed-date column and special handling of closed accounts in net worth.

## Entering balances

### Update balances: all or nothing, no confirmation dialog, nothing written on a date change
A save with any invalid amount saves nothing and says which rows are wrong, so a batch is never half-applied. There is no confirmation dialog on Save: the change column, the "will replace" notes and the footer already show every change before it is made, saving is not destructive (saving the date again edits it), and a dialog on every save gets clicked through. A save sends only the rows the person changed, because resending the prefilled rows would write one person's stale values back over another person's changes. Two people changing the same row stays last-write-wins for now. The form is locked while a save or a date load runs, so an answer can never replace what was just typed. Changing the date writes nothing, and when amounts are typed it asks whether to keep them or clear the form. Leaving the page with typed amounts asks first, because losing ten statement figures is the costly failure. Revisit with a dialog for unusual cases only (overwrites, a balance that changes sign) if mistakes get through.

## Stack and architecture

### Business logic lives in plain functions, and the JSON API is internal
Routes call plain Python functions and add no rules, so a rule is written once and tested without a web server. The JSON API sits over the same functions. It is not a stable contract, so it can change with the frontend.

### A check and the write that depends on it run in one write transaction
Two requests at the same moment can both pass the same check if the check and the write are separate statements: a balance could be entered between "the latest balance is zero" and "close the account", leaving a closed account with a nonzero balance, and two admins could each demote the other and leave no admin. Every operation that reads in order to decide and then writes now runs inside `db.write_transaction`, which takes SQLite's write lock up front (`BEGIN IMMEDIATE`), so the second request waits and then checks against what the first left. Inside an open transaction it joins it. Rejected: database triggers for the invariants, because they hide rules inside the database away from the plain functions and their tests, and retrying on conflict, because a lock that makes the second request wait is simpler and household traffic is tiny. Revisit if writes ever become slow enough that waiting for the lock is noticeable.

### Everything is pinned, updates are reviewed pull requests, and known vulnerabilities fail the build
Python and npm versions, the two base images (by digest) and the CI actions (by commit SHA) are all pinned, so a build is reproducible and nothing changes without a diff. Dependabot opens the updates, and each one goes through CI and a review. The audits (`pip-audit`, and `npm audit` for the runtime dependencies that ship in the bundle) and a Trivy scan of the built image fail a pull request on a known vulnerability, restricted to HIGH and CRITICAL findings that have a fix, because a finding nobody can act on should not block anyone. Build-tool advisories in the frontend are reported but never fail the build, since a build tool cannot affect a running installation. The same workflow runs weekly on `main`, so a newly published advisory shows up there and not first on someone's unrelated pull request. Rejected: auto-merging updates (it would put unreviewed code in a release), and scans that only warn (a warning nobody is forced to read is not a control).

The final image has no pip. The first scan failed on five findings, all in libraries vendored inside pip itself (msgpack, urllib3 and an old setuptools) that the app never uses, so pip is uninstalled once the app is installed. That clears them for good, instead of ignoring them in a scanner configuration, and it means nothing can be installed into a running container. Revisit if something in the image ever needs pip at run time.

### One container and one SQLite file
Household scale, fewest moving parts, simple backup. A live SQLite file is never copied by hand: backups use SQLite's online backup, are checked before they are put in place, and restores move the old database aside.

### React, TypeScript and Vite, served by the same application
The most documentation, and it needs no second container. Same origin, so no CORS. Each frontend dependency needs a stated reason, and versions are pinned exactly.

### No chart library, and no router library
The net worth chart is one simple area drawn as SVG, so a chart library would be weight for no benefit. Routing is about 30 lines of our own code with a leave guard for unsaved work. `react-router` only offers a leave guard in its data-router mode. Revisit the chart decision when a second kind of chart is needed, and the router when routing outgrows seven pages.

## Security

### Local accounts, with no default user
The first admin is created from the command line with a password prompt, so there is nothing to ship or leak and no open signup route. Passwords use scrypt from the standard library, at least 12 characters and no other composition rules. A wrong password and an unknown email look identical in message and timing. Only a hash of the session token is stored, so signing out or changing a password really ends the session on the server. Every signed-in user sees all household data, so there is no per-user data and no per-user permissions beyond the admin role. OIDC is planned and not built.

### Sign-in throttling: three limits, so one attacker cannot block the owner, and a proxy is detected, not configured
Failed attempts are counted in sliding windows against three limits: 5 in 15 minutes per email from one address, 30 in an hour per email from any address, and 20 in 15 minutes per address for any email, the last only when the address can be trusted. A throttle, not a lockout, but any cap on an account can be used by a persistent attacker to slow its owner's sign-in, so the everyday limit is keyed on the email **and** the address: an attacker at another address trips only their own. The account-wide limit is deliberately high so that stopping an attack spread over many addresses does not make blocking the owner cheap. The limiter never looks at the users table and counts unknown emails like real ones, so the answers reveal nothing. A blocked attempt does not check the password, so a correct guess cannot get through, and is not recorded, so a block cannot extend itself. Only hashes are stored, because people paste passwords into the email box.

An attempt takes its slot before the password is checked, in one write transaction. Checking first and recording the failure afterwards would let many simultaneous requests all be checked before any failure was recorded: removing the transaction in a test let 14 of 30 simultaneous attempts through instead of 5.

Behind a proxy every request appears to come from the proxy, so counting by address would let one attacker block everyone, and trusting `X-Forwarded-For` blindly would let an attacker dodge the limit. Uvicorn already replaces the connecting address with the forwarded one only for proxies in `FORWARDED_ALLOW_IPS`, so the app reuses that, and has no setting of its own: if the header is present, the address is trusted exactly when it appears in the header's chain. Otherwise the address limit is off for that request and a warning tells the operator which variable to set. A spoofed header only switches the address limit off for the spoofer, and the email limits still apply. The same limits guard the current-password check on Change password, so a stolen session cannot be used to guess the password. Rejected: a limit of our own for trusted proxies (a second security-sensitive parser of a header, and real addresses would disappear from the access log), and a hard lockout (it hands strangers a way to lock out the owner). Revisit if a household shares one address that is not a real network address, as Docker Desktop can make it, and the address limit trips for everyone. (2026-10-31)

### HTTPS comes from a reverse proxy
The app serves plain HTTP. Sign-in sends a password and a 30-day cookie, so over a network others can see, both could be read. The documentation shows Traefik (automatic certificates) and says plain HTTP is for trying the app out only. The `Secure` cookie flag stays opt-in through `NORTHSTAR_COOKIE_SECURE` because a trial over plain HTTP on a LAN address would otherwise fail to sign in with no explanation, and so the app must log a loud warning when it is off. (2026-10-31)

## Project

### Releases: semantic versions, a release branch per minor version, latest minor only
`main` is development and `release/X.Y` is cut at `vX.Y.0`. Fixes land on `main` first and are backported. This is more machinery than tags alone, but a project others run needs a place to ship a security fix without taking unreleased work with it. Only the latest minor version is supported until 1.0 so a solo maintainer is not committed to old lines. Rulesets enforce the protection once the repo is public. (2026-10-31)

### Docs: a short spec, one decision log, and no screen descriptions
The spec holds scope and rules, this file holds the reasons, the code and tests are the reference for screens and endpoints, and the roadmap becomes GitHub issues. Prose about screens, layouts and endpoints is a second copy of the code, and it had already drifted. Rejected: keeping the spec in Claude project files, because Claude Code cannot read them, changes would no longer be reviewed with the code, and contributors could not see them. (2026-10-31)

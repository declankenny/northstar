# Northstar: backlog

Ideas and follow-ups that are decided to wait. `docs/spec.md` stays the source of truth for scope: an item here is not committed until it moves into the spec. Newest first within each section.

## Auth and access

- **OIDC login (for example Pocket ID).** Modeled on Mealie: client ID and secret and the discovery URL from environment variables, users matched by email, refused unless the IdP says the email is verified, optional user and admin groups from a groups claim, new users created only if signup is enabled. Needs `authlib` and `httpx`, a nullable `password_hash` (or an `auth_method` column), and a test against a fake provider. Local login can then be switched off.
- **First-run setup page** that creates the first admin when there are no users. Planned for v0.2 (see `docs/spec.md`, "Release and distribution"). Only with a guard such as a one-time token printed in the container log, because it is an unauthenticated route that grants admin. Until then the first admin is created from the command line. Decided 2026-10-31: the sign-in page stays the one server-rendered page (a React sign-in would need the app shell to be public, a public JSON login endpoint and a new 401 flow, and OIDC would replace the form anyway). If this page is built, build it and the sign-in screen in React together as their own PR: that also removes Jinja2 and the `templates` folder.
- **Login rate limit or lockout** after repeated failures. Now required before v0.1.0, because others will expose their copies to the internet: it moved into the spec ("Release and distribution").

## Frontend

- **Page state in the address.** Addresses are clean paths now (see `docs/spec.md`, "Addresses"). The next step would be state in the query string, such as `/balance-update?date=2026-10-28` or the Open/Closed choice on `/accounts`, so a view can be bookmarked. Not needed yet.

## Product

- Items from "After v1" in the spec (SimpleFIN pull, loan details, CSV import and export, and so on) are tracked there until they are scheduled.

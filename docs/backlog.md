# Northstar: backlog

Ideas and follow-ups that are decided to wait. `docs/spec.md` stays the source of truth for scope: an item here is not committed until it moves into the spec. Newest first within each section.

## Auth and access

- **OIDC login (for example Pocket ID).** Modeled on Mealie: client ID and secret and the discovery URL from environment variables, users matched by email, refused unless the IdP says the email is verified, optional user and admin groups from a groups claim, new users created only if signup is enabled. Needs `authlib` and `httpx`, a nullable `password_hash` (or an `auth_method` column), and a test against a fake provider. Local login can then be switched off.
- **First-run setup page** that creates the first admin when there are no users. Only with a guard such as a one-time token printed in the container log, because it is an unauthenticated route that grants admin.
- **Login rate limit or lockout** after repeated failures. Not needed on a local-only app, but needed before the app is exposed beyond the household.
- **Gate some screens on `is_admin`** (for example Account types) once there is a reason.

## Frontend

- **URL design and cleanup.** The React app uses hash URLs (`/app/#/profile`, `/app/#/users`) so it needs no router library and no server change. Once more screens move into React (Accounts, Update balances, Account types, Account detail), switch to clean paths such as `/app/users`: a catch-all route in FastAPI that serves the bundle's `index.html` for any `/app/...` path, and a small history-based router in the frontend (about 30 lines, no dependency, or `react-router` if the routing needs grow). Decide at the same time how the classic server-rendered URLs map to the new ones (redirects from the old pages), and keep the `next` redirect after login working with the new paths.

## Product

- Items from "After v1" in the spec (SimpleFIN pull, loan details, CSV import and export, and so on) are tracked there until they are scheduled.

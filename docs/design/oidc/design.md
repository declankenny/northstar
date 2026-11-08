# OIDC sign-in: design

Status: drafted on November 8, 2026. Nothing here is built. Each section says what is decided, what is proposed and what is open. Anything marked TODO is unresolved and must not be guessed.

## What it is

Northstar supports sign-in through one OpenID Connect provider. A successful sign-in resolves to an ordinary Northstar user and starts an ordinary Northstar session. User ids, household access and audit history stay in Northstar. Administrator status stays managed in Northstar (provider role synchronization is deferred to #163).

Every signed-in user sees all household data. So `oidc.user.allow_creation` is not a registration switch for a private account: turning it on gives household financial access to whoever the provider admits to Northstar's client. The property's hint says so.

## Decided

| Topic | Decision |
|---|---|
| Release | v0.4, its own minor release. |
| Protocol | Standard OIDC, authorization code flow with PKCE (S256), through a maintained library. Northstar owns admission, policy, persistence and sessions. |
| Providers | One configured provider. |
| Settings | Ordinary settings are `oidc.*` system properties. |
| Client secret | Deployment configuration or a secret file, never a system property and never in the change log. |
| User creation | `oidc.user.allow_creation`, default false. |
| Email | A verified email (`email_verified` exactly true) is required to link or create. |
| Linking | A matching verified email links an existing active user, with no local-password confirmation, even when creation is off. |
| OIDC session | Absolute lifetime from `oidc.session.lifetime_hours`, default 12, not extended by use. |
| Local sign-in | `system.auth.local.enabled`, default true. |
| Profile | Name and email are copied at creation only. |
| Roles | Not synchronized. New users are regular users, linked users keep their role. The provider's role claim is ignored. |
| Logout | Ends the Northstar session only. |
| Password hash | An OIDC-created user has an unusable password hash, as the system user has. |
| Identity table | `user_identities` is a household table (audit columns, `AUTOINCREMENT`, written through the writer with an operation), not a `sys_` table. |
| Revocation | No hook on property changes. A session and a login transaction record which provider configuration they belong to, and are refused when it no longer matches (see "Sessions"). |

## Not in v0.4

Role synchronization (#163), provider-wide logout, back-channel logout, refresh tokens, keeping provider tokens, SCIM or directory synchronization, several providers, an unlink or re-link screen, a profile linking wizard, and recovery when no active administrator exists (#158).

## Properties and deployment settings

| Name | Kind | Default | Purpose |
|---|---|---|---|
| `oidc.enabled` | Boolean | false | Offer and accept OIDC sign-in. |
| `oidc.provider` | String, may be unset | unset | Display label for the button. It selects no behavior. |
| `oidc.issuer` | String, may be unset | unset | The exact issuer URL, used for discovery and token validation. |
| `oidc.client_id` | String, may be unset | unset | The registered client id. |
| `oidc.user.allow_creation` | Boolean | false | Create a user on the first sign-in of an unknown verified identity. |
| `oidc.session.lifetime_hours` | Integer | 12 | Lifetime of new OIDC sessions. Existing sessions keep theirs. |
| `system.auth.local.enabled` | Boolean | true | Allow password sign-in, in the form and at the endpoint. |

Deployment settings (environment variables, so they count as breaking in the changelog):

- `NORTHSTAR_OIDC_CLIENT_SECRET_FILE`, or as the alternative `NORTHSTAR_OIDC_CLIENT_SECRET`. Both set is a startup error. The value never appears in an API response, a log or the change log. The settings screen may say whether a secret is available.
- `NORTHSTAR_PUBLIC_URL`: the address people reach Northstar at, used to build the callback address. It is never derived from the `Host` or forwarded headers. OIDC needs it to be HTTPS (and `NORTHSTAR_COOKIE_SECURE=1`), with a documented exception for `localhost` development. TODO: confirm the exact exception.

Proposed: the validators stop an incomplete or contradictory configuration from being saved, as `catalog_currency` does:

- `oidc.enabled` cannot be turned on until issuer, client id, the secret and the public URL are all present.
- `system.auth.local.enabled` cannot be turned off unless OIDC is enabled and complete, and at least one active administrator has an identity for the configured issuer. This is the guard against locking everyone out. Signing in once through OIDC as that administrator before switching local sign-in off is recommended in the operator guide.
- `oidc.enabled` cannot be turned off, and `oidc.issuer` cannot be changed, while local sign-in is off, unless the result still leaves a linked active administrator (a changed issuer leaves none, so it is refused until local sign-in is back on).

**Open: a Boolean data type.** The property types are String, Integer, Lookup, Date and Time. Recommendation: add a Boolean type (a checkbox, stored as text `true` or `false`, null refused), because three properties need it and later ones will too. The alternative is a Lookup with two options, which adds no type but reads badly in code and in the editor. It changes the spec's property rule either way.

## Identity resolution

After the library has validated the ID token (signature, algorithm, exact issuer, audience and authorized party, expiry, nonce), apply these in order:

1. If `(issuer, subject)` is already bound, use that user. A deleted or system user is refused. A known identity is never re-matched by email.
2. Otherwise require a valid email and `email_verified` equal to the boolean true. A missing claim, the string `"true"` or any other type is refused. Normalize the email as Northstar does everywhere. An address ending in `.invalid` is refused.
3. If the email belongs to an active, non-system user, bind this identity to that user and sign in as them. Their profile and role are kept. This creates no user, so it is allowed when creation is off.
4. If the email belongs to a deleted user, refuse. Never reactivate.
5. If no user has the email, require `oidc.user.allow_creation`. Create a regular user and bind the identity in one transaction, with the system default theme and locale and an unusable password hash. The display name is the provider's name claim if it is usable, otherwise the email. TODO: the name rules (length, blank) follow the existing user rules, to be checked against `northstar/users.py`.

One identity per issuer per user: a second subject presenting an email already bound to another identity for that issuer is refused, not substituted. Replacing a binding is a future administrative procedure.

All of this runs in one write transaction with unique constraints, so two first sign-ins at once produce one user and one identity, and a conflict is re-checked and never merges accounts. Before commit it re-reads the current configuration and the user's deleted status.

Refusals: one plain message for "no account and creation is off", a deleted user and a system user, so the sign-in page does not say which. A different, actionable message for an unverified or missing email. TODO: confirm the wording with the mockup.

**Trust this creates.** Linking by email trusts the configured provider to verify ownership of every existing Northstar address, administrators' included. A provider administrator who can assert a verified email can sign in as that user. That is the agreed policy. It must be in `SECURITY.md` and the operator guide. Whether Authentik and Pocket ID send `email_verified` as a real boolean by default is TODO: it is checked against both real providers (step 5), not assumed.

## Sign-in flow

1. The person clicks Continue with the provider on `/login`.
2. Northstar makes a login transaction: random state, nonce, PKCE verifier, a safe return path (the existing `safe_next` rules), a browser-binding value and the configuration fingerprint. It lives in a `sys_` table for 10 minutes (a constant, not a property) and sets a random `HttpOnly`, `Secure`, `SameSite=Lax` binding cookie. State and the binding value are stored as hashes.
3. Northstar redirects to the provider's authorization endpoint (found by discovery from the configured issuer) with scopes `openid profile email`.
4. The callback is a GET with the code in the query string. It verifies state, the binding cookie, expiry and the fingerprint, and consumes the transaction once, successful or not.
5. The server exchanges the code and has the library validate the ID token. UserInfo is not used. Only the ID token's claims are read.
6. Resolution (above), then a fresh Northstar session replaces any session the browser had, and the person is redirected to the return path.

Both endpoints are exact public paths added to the public list in `northstar/web/app.py`, and nothing else becomes public: `/api/auth/oidc/login` and `/api/auth/oidc/callback` (names proposed; they sit under `/api`, so they do not touch the reserved page names). A small public endpoint tells the sign-in page which methods are on and the button label, and carries no secret. TODO: its path.

The cross-site refusal for changes from another site is unchanged: the callback is a GET that creates a session, which is the standard flow, protected by state, the binding cookie and PKCE rather than by the Origin check.

Outbound requests: discovery, token exchange and key fetches go only to the configured issuer, with certificate verification, short timeouts, a response size limit and no visitor-supplied URL. A provider on a private network is allowed because the administrator chose it. The spec's rule that Frankfurter is the only host Northstar calls changes in the building pull request, and the client secret is now a credential Northstar sends. Throttling reuses the existing failed-attempt tracking where it fits, and a provider outage is not counted as a wrong password. TODO: how `sys_login_attempts` keys are reused.

Errors from the provider show a plain message on the sign-in page and never the raw response, a token or the code.

## Sessions and logout

`sys_sessions` gains the sign-in method (`local` or `oidc`), a configuration fingerprint (null for local) and keeps its expiry column, which now holds whatever lifetime applied at issue. Existing rows migrate as local with their expiry. A local session stays 30 days. An OIDC session expires `oidc.session.lifetime_hours` after sign-in and use does not extend it. At expiry the person signs in again, and the provider may need no interaction.

**Why no revocation hook.** The fingerprint is a hash of the issuer and client id. The request middleware refuses an OIDC session whose fingerprint differs from the current configuration, or when `oidc.enabled` is false, and the callback refuses a transaction in the same cases. So changing the provider or turning OIDC off ends its sessions without code in the setting service. Rows that no longer match are deleted by the existing expiry sweep.

The secret is not in the fingerprint, so rotating it ends nothing. Removing someone at the provider stops future sign-ins but not a live session, which the lifetime bounds. Deleting a Northstar user still ends their sessions at once. Logout deletes the Northstar session and cookie only.

Turning local sign-in off does not end local sessions. It stops new password sign-ins, enforced at the endpoint as well as in the page.

## Data

- `user_identities`: id (`AUTOINCREMENT`), user_id, issuer, subject and the audit columns. Unique on (issuer, subject) and on (user_id, issuer). Logged fields: user_id, issuer and subject. Never a token or a raw claim set.
- Bindings are kept when a user is deleted, so a later sign-in cannot get around the deletion. Generic undo never restores or reassigns a binding.
- A new `sys_` table for login transactions, with no audit columns and written without an operation.
- `sys_sessions` columns as above.
- New users and bindings are written by a provisioning service, not the password-based `add_user`, with the system user as author and an operation that says it was OIDC provisioning or linking.
- Migration, `docs/schema.md`, `sys_audited_fields`, the writer's rules and the backup check all account for the new tables and columns.

Showing methods: Users lists Local, OIDC, or Local and OIDC. TODO: how a user with no usable password is detected (the system user's marker hash is the model, to be checked against `northstar/users.py`). An OIDC-only user's profile explains how they sign in instead of showing a current-password form that cannot succeed. An admin's password reset can still give a local password, and the global local-sign-in setting still applies.

## Recovery

The switch that turns local sign-in off needs a way back that works with no provider and no web session. Proposed: a host-only command that sets `system.auth.local.enabled` to true through the setting service, authored by the system user as a `cli` operation, and refuses a database the app has not migrated, like the other tools. Its name is TODO (it sits beside `python -m northstar.users set-password`). It ships in the same release as the switch, and is documented in the operator guide. After it, `set-password` can give an active administrator a local password. Recovery with no active administrator is #158 and is not solved here.

## Library and dependencies

TODO: choose and pin. Authlib's Starlette integration is the first candidate. Before committing, check that it supports Python 3.15 and the pinned FastAPI, that `pip-audit`, `npm audit` and Trivy stay green, and what it pulls in. Two costs are already known: `httpx` is today a development-only dependency and would become a runtime one, and JWT signature checking brings a cryptography package into the image. The reason for each goes in the pull request and `decisions.md`. Northstar writes no cryptography itself.

## Tests

- A fake provider in the test suite (its own signing key, discovery document and token endpoint, served through httpx's mock transport), covering every acceptance row below. Mutation checks on the identity-resolution conditions and on the fingerprint check, as the lock statements were checked for the scheduler.
- Acceptance: existing local sign-in, setup, admin rules, password reset and the change log still work; defaults keep local sign-in on, OIDC off and creation off; unknown verified identity creates a regular user only when creation is on; verified email links an existing active user with creation off and keeps their role; missing, false or non-boolean `email_verified` neither links nor creates; deleted and system users never sign in and are never reactivated; a known identity survives a changed email or name; a second subject with a bound email is refused; duplicate callbacks and concurrent first sign-ins make one user and one session; bad signature, issuer, audience, nonce, state, binding cookie, an expired or already used transaction and a changed fingerprint are all refused; return paths stay local; no secret, token or code in a log, a response or the change log; the lifetime is absolute; logout ends only Northstar's session; local sign-in off is enforced in page and endpoint and the validators refuse every lock-out configuration; changing issuer or client id, or turning OIDC off, ends OIDC sessions; the recovery command works with no provider.
- Real Authentik and Pocket ID, by hand, before the release candidate: link, create, error paths and what `email_verified` actually contains.

## Documents that change with the code

`spec.md` (scope, data model, users and roles, sessions, access, outbound requests, system properties and the new Boolean type), `decisions.md`, `schema.md`, `SECURITY.md` (the provider trust above), `operating.md` (client registration, callback address, verified email, secret and its rotation, switching local sign-in off, recovery), `CHANGELOG.md` with a **Breaking** entry for the migration and the new environment variables, and the README environment table.

## Open before building

- Boolean type or two-option Lookup (above).
- What `email_verified` holds in Authentik and Pocket ID (TODO, checked at step 5).
- Library choice, versions and Python 3.15 support (TODO).
- The localhost exception for the public URL, the public options endpoint path, the recovery command's name, the exact refusal wording, the display-name rules and the unusable-hash marker (each TODO above).

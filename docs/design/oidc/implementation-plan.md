# OIDC sign-in: implementation plan

Five steps, each its own branch and pull request into `main`, all in milestone v0.4. Each step changes the spec and decisions log for the rules it builds, in the same pull request. The issues are under [#67](https://github.com/declankenny/northstar/issues/67). All five steps were built and released in v0.4.

| Step | What | Issue |
|---|---|---|
| 1 | Settings: the Boolean data type (if chosen), the `oidc.*` and `system.auth.local.enabled` properties, secret and public URL loading, the lock-out validators, the host recovery command | [#166](https://github.com/declankenny/northstar/issues/166) |
| 2 | Storage and resolution: migration for `user_identities`, the login-transaction table and the session columns, session lifetime and method, the provisioning service and identity resolution, with tests | [#167](https://github.com/declankenny/northstar/issues/167) |
| 3 | The flow: the library and its pin, the two public routes, cookies, the fingerprint check in the middleware, throttling, the fake-provider tests | [#168](https://github.com/declankenny/northstar/issues/168) |
| 4 | Interface: the sign-in page choices, the public options endpoint, Users showing the methods, the profile for OIDC-only users, the System properties hints | [#169](https://github.com/declankenny/northstar/issues/169) |
| 5 | Validation and operator documents: real Authentik and Pocket ID runs, the operator guide, `SECURITY.md`, the changelog, the release candidate | [#170](https://github.com/declankenny/northstar/issues/170) |

Not planned for v0.4: role synchronization ([#163](https://github.com/declankenny/northstar/issues/163)) and recovery with no active administrator ([#158](https://github.com/declankenny/northstar/issues/158)).

## Step 1

- **Scope:** `northstar/system_properties.py` and its editor, `northstar/config.py` for the secret and the public URL, a new migration for the properties, and the recovery command.
- **Why first:** every later step reads these, and the lock-out guard has to exist before local sign-in can be switched off.
- **Settled in it:** the Boolean type (a Yes/No dropdown) and the recovery command, `python -m northstar.signin enable-local`.

## Step 2

- **Scope:** `northstar/sessions.py` (duration and method), a new provisioning module, the migration, `docs/schema.md`, the audited-fields list and the writer's rules.
- **Tests:** every row of identity resolution, concurrent first sign-ins, deleted and system users, with mutation checks on the conditions.
- **Settled in it:** the unusable-hash marker (a stored hash that is not a well-formed scrypt hash) and the display-name rules.

## Step 3

- **Scope:** `northstar/oidc.py` (the flow), `northstar/web/oidc_routes.py`, `app.py` (public paths and the fingerprint check) and `auth_routes.py` (password sign-in refused when it is off), `joserfc` and `cryptography` as new dependencies with their stated reason.
- **Settled in it:** joserfc instead of Authlib, and the enforcement of local sign-in being off, which moved here from step 4.

## Step 4

- **Scope:** the sign-in page, Users and the profile in `frontend/src`, with mockups agreed first, and the public `GET /api/auth/methods`. Nothing in the frontend decides who may sign in.

## Step 5

- **Scope:** documents and a manual run against both providers, then the release process (release candidate, rehearsal, final release).
- **Settled in it:** what `email_verified` contains was checked for Pocket ID only; Authentik was not checked.

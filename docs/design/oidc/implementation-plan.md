# OIDC sign-in: implementation plan

Five steps, each its own branch and pull request into `main`, all in milestone v0.4. Each step changes the spec and decisions log for the rules it builds, in the same pull request. The issues are created when the milestone is planned in detail, under [#67](https://github.com/declankenny/northstar/issues/67); until then the issue column is TODO.

| Step | What | Issue |
|---|---|---|
| 1 | Settings: the Boolean data type (if chosen), the `oidc.*` and `system.auth.local.enabled` properties, secret and public URL loading, the lock-out validators, the host recovery command | TODO |
| 2 | Storage and resolution: migration for `user_identities`, the login-transaction table and the session columns, session lifetime and method, the provisioning service and identity resolution, with tests | TODO |
| 3 | The flow: the library and its pin, the two public routes, cookies, the fingerprint check in the middleware, throttling, the fake-provider tests | TODO |
| 4 | Interface: the sign-in page choices, the public options endpoint, Users showing the methods, the profile for OIDC-only users, the System properties hints | TODO |
| 5 | Validation and operator documents: real Authentik and Pocket ID runs, the operator guide, `SECURITY.md`, the changelog, the release candidate | TODO |

Not planned for v0.4: role synchronization ([#163](https://github.com/declankenny/northstar/issues/163)) and recovery with no active administrator ([#158](https://github.com/declankenny/northstar/issues/158)).

## Step 1

- **Scope:** `northstar/system_properties.py` and its editor, `northstar/config.py` for the secret and the public URL, a new migration for the properties, and the recovery command.
- **Why first:** every later step reads these, and the lock-out guard has to exist before local sign-in can be switched off.
- **Open before it starts:** the Boolean decision and the recovery command's name.

## Step 2

- **Scope:** `northstar/sessions.py` (duration and method), a new provisioning module, the migration, `docs/schema.md`, the audited-fields list and the writer's rules.
- **Tests:** every row of identity resolution, concurrent first sign-ins, deleted and system users, with mutation checks on the conditions.
- **Open before it starts:** the unusable-hash marker and the display-name rules.

## Step 3

- **Scope:** `northstar/web/auth_routes.py` and `app.py` (public paths and the fingerprint check), the library integration, a new dependency and its stated reason.
- **Open before it starts:** the library, its pin and Python 3.15 support.

## Step 4

- **Scope:** the sign-in page, Users and the profile in `northstar/web/spa`, with mockups agreed first. Nothing in the frontend decides who may sign in.

## Step 5

- **Scope:** documents and a manual run against both providers, then the release process (release candidate, rehearsal, final release).
- **Open before it starts:** what `email_verified` contains in each provider.

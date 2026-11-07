# First-run setup

Status: design agreed on November 7, 2026, including an interactive UI mockup, and implemented in the pull request for [#64](https://github.com/declankenny/northstar/issues/64), which also changed the specification and the decisions log. This document records the agreed design.

## Purpose and scope

Create the first administrator and set the most important system properties in one pass. The administrator and properties are saved together, then the person signs in normally. There is no intermediate state in which the administrator has been created but initial configuration still needs completing.

This is sequence 6 of the [v0.3 implementation plan](currency/implementation-plan.md), following completion of sequences 1–5.

The setup PR removes `python -m northstar.users create`, retains `python -m northstar.users set-password EMAIL`, and updates the operating guide. The plan currently calls the retained command `reset-password`; correct that documentation to `set-password` in the setup PR. This is not a command rename.

Recovery when no active administrator remains is a separate, unscheduled feature: [#158](https://github.com/declankenny/northstar/issues/158). It is not a dependency of setup. Forgotten-password recovery continues to use `set-password`.

## Eligibility and entry

Reserve `/setup` for first-run setup. Eligibility depends only on whether a non-system administrator row exists. Deleted administrator rows count; the internal system user does not.

- No such administrator: setup is available with a valid setup token.
- An active or deleted administrator exists: setup is unavailable.
- A visit to `/setup` after completion goes to sign-in. Setup API requests are refused by the server.

Counting deleted administrators prevents deletion from reopening setup. It checks the administrator rows that remain; it is not a separate historical record that setup once ran. Normal application actions already prevent deleting or demoting the last active administrator.

## UI

Use the existing sign-in page's branding, typography, light/dark themes, inputs and buttons. There is no authenticated sidebar. The agreed mockup has a centered form with administrator details above household settings. Display name and email share a row where space permits; fields stack on narrow screens.

The wireframes below preserve the content and hierarchy of the approved interactive mockup. They are schematic rather than pixel-accurate. Preview navigation used to inspect the mockup is not part of the product.

### Token entry

```text
Northstar

Welcome to Northstar
Enter the setup token from your container log to get started.

  Setup token
  [ Paste your setup token                               ]

  [ Continue to setup                                    ]
```

The token is pasted into a field, not supplied in a URL. A valid token unlocks the setup form; it does not create an administrator or consume the token.

### Setup form

```text
Northstar

Set up Northstar
Create your administrator account and choose your household settings.

  Your administrator account

  Display name                    Email
  [ Alex Morgan               ]   [ alex@example.com     ]

  Password
  [                                            ] [ Show ]
  At least 12 characters.

  Confirm password
  [                                                      ]

  This account can manage users and system settings.

  Household settings

  Household reporting currency
  [ Search by currency name or code                      ]
  Used for household totals. Individual accounts can use
  other currencies.
  Choose carefully. This cannot be changed after setup.

  Default number and date format
  [ English (United States)                            v ]
  1,234.56 · Nov 7, 2026
  Used for your account and as the default for new users.
  Each person can change their own format.

  Time zone
  [ America/Chicago                                      ]
  Controls today's date and when scheduled jobs run.

  [ Create administrator and finish setup                 ]

  You'll sign in with your new account when setup is complete.
```

Names, email, time zone and the preview date above are illustrative. Name and email start empty. The time zone starts from the installation's stored configuration, not from the example above.

Administrator fields:

- Display name and email use existing user validation.
- Password uses the existing minimum of 12 characters, with show/hide support and a confirmation field.
- The account is always an administrator; there is no role selector.

Initial properties:

| UI label | Property | Behaviour |
| --- | --- | --- |
| Household reporting currency | `system.currency` | Required if unset; no preselected currency. Search the currency catalog by name or code. Choosing it locks it, with a visible warning before submission. An existing locked value is shown read-only and preserved. |
| Default number and date format | `ui.locale.default` | Start from the stored default. Offer the supported locale catalog and update number/date examples when the selection changes. Apply the selected locale to the new administrator as well as future users. |
| Time zone | `system.timezone` | Start from the stored installation value. Choose a valid IANA time zone. It controls today and scheduled jobs. |

Theme, balance and rate staleness thresholds, exchange-rate history start, and rate fetch time retain their existing defaults. They are not setup fields. The implementation uses the full supported currency and time-zone choices; the interactive mockup's abbreviated lists were for preview only.

### Completion and sign-in

```text
Northstar

Setup complete
Your administrator account and household settings are ready.

  Sign in to Northstar

  Email
  [ alex@example.com                                     ]

  Password
  [                                                      ]

  [ Sign in                                              ]
```

Use normal sign-in after successful setup, with a completion message and the entered email available to prefill the form. Do not automatically sign in the administrator. Do not retain or prefill the setup password.

## Token and setup-session lifecycle

1. At application startup, check eligibility. If an administrator exists, generate no token.
2. If eligible, generate a cryptographically random token and print it once in the container log alongside the `/setup` address. Keep the token out of URLs and request logs. Printing this bootstrap token is the deliberate exception to the usual prohibition on logging credentials; passwords and setup-session credentials must not be logged.
3. A valid token grants that browser a setup session through an `HttpOnly` cookie. This session authorizes only setup, never household data or normal authenticated APIs.
4. The printed token remains valid until successful setup or application restart. A browser setup session lasts 30 minutes. If it expires, entering the token again grants a new setup session.
5. Restarting before completion generates a new token and invalidates prior tokens and setup sessions.
6. Completing setup rechecks eligibility and setup-session authorization. Only a successful commit consumes setup authorization. Every token and setup session is then unusable, including sessions in other browsers.

Token verification does not consume the token. Form validation errors do not consume it either. Incorrect token attempts receive a generic error and are throttled.

## Transaction and audit

Administrator creation and property changes form one atomic transaction. Recheck eligibility under the database write lock so concurrent submissions cannot both create administrators.

Within the transaction:

1. Create the administrator, attributed to the internal system user because nobody is signed in yet.
2. Save changed initial properties through the existing settings service, using the new administrator's ID as the actor. Set the administrator's locale explicitly to the selected locale rather than inadvertently copying the previous default.
3. Commit everything together. Any validation or write failure rolls everything back.

For changed properties, `updated_by` is the new administrator and `updated_at` records the change. Their original `created_by` and `created_at` remain unchanged. A save whose normalized value is unchanged makes no write: it never touches `updated_by` or `updated_at`. An existing read-only currency is preserved without attempting an update through the settings service.

The existing property service continues to enforce validation, currency locking and enabling, and audited writes. Setup must not introduce a direct-write path that bypasses those rules.

## Edge cases

| Situation | Agreed behaviour |
| --- | --- |
| Incorrect token | Generic error; throttle attempts; create no setup session. |
| Invalid administrator field or property | Save nothing. Keep setup authorization valid and show field errors. |
| Setup session expires while the form is open | Ask for the token again. Preserve non-password fields in browser memory and clear passwords. |
| Application restarts while the form is open | Require the new token from the container log. Preserve non-password fields in browser memory and clear passwords. |
| Two browsers submit together | One transaction succeeds. The other is refused with “Setup has already been completed” and a sign-in link. |
| Commit succeeds but the response is lost | A retry cannot create another administrator. Show setup complete and direct the person to sign-in. |
| Database write fails | Roll back the administrator and property changes together; allow retry. |
| `/setup` is visited after completion | Redirect to sign-in; refuse setup API writes on the server. |
| Reporting currency already set and locked | Show the stored currency read-only and preserve it. |
| Locale and time zone already configured | Start with the stored values. |
| Submitted email belongs to an existing user, including a deleted user | Refuse it; do not silently promote or reactivate that user. Broader recovery belongs to #158. |
| Only deleted administrator rows remain | Setup remains closed; recovery is separate. |

Preserving fields in browser memory does not promise persistence across a page reload. Passwords, tokens and setup-session credentials are not stored in browser local storage.

## Implementation details to resolve

The product behaviour above is agreed. The implementation still needs concrete choices for token entropy and storage, setup-session storage and cookie scope, throttling limits, and API response shapes. These must preserve the agreed expiry, restart invalidation and concurrency behaviour. Check the actual server process model when choosing storage; do not assume independent worker memory can provide one consistent token lifecycle.

Apply the existing same-origin protections and security headers to setup. Setup authorization must be checked on the server for both access to setup data and the final write. Distinguish an expired authorization from completed setup without exposing household data.

## Verification and documentation in the implementation PR

- Verify a fresh installation through token entry, form completion and normal sign-in.
- Verify eligibility with active administrators, deleted administrators and the internal system user.
- Verify wrong tokens, throttling, session expiry, restart invalidation and authorization reuse after completion.
- Verify concurrent submissions create exactly one administrator and response-loss retries cannot duplicate it.
- Verify rollback on property validation and database failure, including failures after administrator creation.
- Verify property authorship, unchanged-value no-ops, preserved creation metadata and the administrator's selected locale.
- Verify existing locked currency and configured defaults, and refusal of an existing user's email.
- Verify direct API access cannot bypass setup authorization or the completed-setup guard.
- Verify responsive layout, keyboard operation, field errors and both themes against the agreed mockup.
- Update `docs/spec.md`, `docs/decisions.md`, `docs/operating.md`, affected first-admin instructions and the implementation plan with the code. Correct `reset-password` references to `set-password` and remove `users create` instructions.
- If storage requires a migration, follow the existing migration, backup, restore and upgrade checks using synthetic data or an authorized database copy.

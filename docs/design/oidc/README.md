# OIDC sign-in

The design for v0.4: sign-in through one OpenID Connect provider (Authentik, Pocket ID or similar), alongside the existing local sign-in.

- [design.md](design.md): what OIDC sign-in does and why, the rules, what is decided, what is proposed and what is still open.
- [implementation-plan.md](implementation-plan.md): the steps and the issues they close.

Issues: [#67](https://github.com/declankenny/northstar/issues/67) (OIDC sign-in, milestone v0.4) and its steps [#166](https://github.com/declankenny/northstar/issues/166), [#167](https://github.com/declankenny/northstar/issues/167), [#168](https://github.com/declankenny/northstar/issues/168), [#169](https://github.com/declankenny/northstar/issues/169) and [#170](https://github.com/declankenny/northstar/issues/170). Deferred: [#163](https://github.com/declankenny/northstar/issues/163) (role synchronization from the provider). Related: [#158](https://github.com/declankenny/northstar/issues/158) (recovery when no active administrator remains).

## Where it came from

A proposal dated November 8, 2026 (kept outside the repository) was reviewed against `docs/spec.md`, `docs/roadmap.md` and #67 the same day. The review removed role synchronization (#163), replaced a revocation hook with a check at request time, and settled that OIDC users have an unusable password hash and that `user_identities` is a household table with audit columns, not a `sys_` table.

This folder is not the spec or the decisions log. They change with the code, in `docs/spec.md` and `docs/decisions.md`. It is deleted only when Declan says so.

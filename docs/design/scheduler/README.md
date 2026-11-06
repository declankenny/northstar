# In-app scheduler

The design for jobs that run inside Northstar once a day at a time an admin sets, starting with the exchange-rate fetch.

- [design.md](design.md): what the scheduler does and why, the lock, failures, shutdown and the numbers.
- [implementation-plan.md](implementation-plan.md): the steps and the issues they close.

Issues: [#138](https://github.com/declankenny/northstar/issues/138) (the scheduler), [#152](https://github.com/declankenny/northstar/issues/152) (the time zone), [#131](https://github.com/declankenny/northstar/issues/131) (the rate fetch). Deferred: [#154](https://github.com/declankenny/northstar/issues/154) (manual runs) and [#155](https://github.com/declankenny/northstar/issues/155) (a Jobs screen).

This folder is not the spec or the decisions log. They change with the code, in `docs/spec.md` and `docs/decisions.md`. It is deleted only when Declan says so.

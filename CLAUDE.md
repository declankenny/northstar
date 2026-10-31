# CLAUDE.md: finance tracker

## What this is

A self-hosted tracker of household financial position over time, run as a docker container on Declan's home server (`the deployment host`). `docs/spec.md` is the source of truth for scope. v1 is manual balance entry only: no transactions and no bank feeds.

## Working rules

- Read `docs/spec.md` before starting any task. If a request conflicts with it, say so and ask.
- On anything touching servers, containers or deployment, work one step at a time: give a single action, wait for the result, then continue.
- Push back directly when something adds more complexity than v1 needs. Explain what future need would justify it and recommend the simpler option.
- Mark unknown or unverified information as TODO. Do not infer it. Look facts up instead of guessing.
- Verify before claiming done: run the tests, run the app, and look at the result.

## Git

- One feature branch per task, pull request into `main`. TODO confirm branch naming and review process.
- When a task is done and verified, commit it to the feature branch, push it and open the pull request. Declan reviews the diff in the pull request, so do not ask for approval before committing. The pull request description says what changed, what was verified and what was not.
- Never merge pull requests, force-push, rewrite shared history, delete branches or tags, or commit to `main`.

## Data and secrets

- Never commit, log or print secrets, tokens, credentials or `.env` contents. Refer only to where they are stored.
- This is real financial data. No real balances, account numbers or institution credentials in the repo, tests, fixtures, logs or chat. Tests use synthetic data.
- A future SimpleFIN access URL is a credential. Store it like a secret and never log it.

## Code

- Money is integer cents. Never floating point.
- Balances are calendar dates with no timezone. The app has no timezone logic in v1: "today" is the machine's date, read in one `today()` function.
- Keep dependencies few. Each new one needs a stated reason.
- Schema changes ship as migrations and are tested on a copy of the database first.

## Deployment

- Out of scope until v1 runs locally. Deploying means a stack in Declan's `the deployment repo` repo through that repo's PR workflow. Do not touch that repo or the server without approval.

# Contributing to Northstar

Thank you for thinking about it. Northstar is a small project kept by one person, so a short conversation before you build something saves everyone time.

## Before you start

- **Open an issue first** for anything bigger than a typo or an obvious bug fix, and say what you want to change and why. Northstar deliberately does less than other finance tools (no transactions, no budgets, no bank feeds yet). `docs/spec.md` says what is in scope today, and `docs/roadmap.md` says what is planned, what is on the backlog and what is not planned. A good idea that does not fit may be declined, and it is kinder to find that out before you write the code.
- **`docs/spec.md` is the source of truth** for scope and rules. A change to a rule changes the spec in the same pull request, and a decision worth explaining gets an entry in `docs/decisions.md`, also in the same pull request.
- **Security problems are not issues.** Report them privately, as described in [SECURITY.md](SECURITY.md).

## Setting up

You need Python 3.15 and Node.

```
pip install -e ".[dev]"
cd frontend && npm ci
```

Use synthetic data only, always: no real balances, account numbers or credentials in code, tests, fixtures, logs, issues or screenshots. Never point a development copy at a real database file.

## Making a change

1. Branch from `main`, named `feature/<name>` for new work or `fix/<name>` for a bug fix. One branch for one task.
2. Write the tests with the change. A bug fix starts with a test that fails for the bug. Run them before you push:

   ```
   python -m pytest        # Python tests
   cd frontend && npm test # frontend tests (charts are tested as DOM in jsdom: see the comment at the top of frontend/src/charts/Chart.test.tsx)
   ```

3. If you changed how the app looks or behaves, run it and look at the result. A passing test suite is not the same as a working screen.
4. Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) when a user would notice the change. Anything that touches the database (a migration), an environment variable or the backup format goes under a **Breaking** heading, because those always count as breaking before 1.0.
5. Open a pull request into `main`.

## The rules the code follows

- Money is integer cents, never floating point. Dates are calendar dates with no timezone.
- Business logic lives in plain Python functions, and routes call them without adding rules.
- A schema change is a forward-only migration, and a released migration is never edited.
- Each new dependency needs a reason, and the project keeps them few. Versions are pinned exactly.

## Locales

The number and date formats are rows of `ref_locales`, loaded by a migration that `scripts/generate_locales.py` writes from the Unicode CLDR. Nothing at run time reads CLDR, and Babel, which reads it, is a development dependency only. To add a locale, put it on the allowlist in the script, run `python scripts/generate_locales.py` (it needs Node, to cross-check the result) and then `--write` into a new migration, and review the rows. The script refuses a locale whose conventions go beyond the rules in `docs/design/locale.md`. The tests fail if the migrated rows differ from what the script generates.

## Pull requests

The pull request description says **what changed**, **what was verified** and **what was not**. The template asks for these, and being honest about the last one is the most useful thing you can write.

Every pull request needs the CI checks to pass: the Python tests, the frontend checks, the dependency audit and the Docker image build. The maintainer reviews the diff and merges it. This is one person's spare time, so a review can take a few days, and the maintainer may ask for changes or decline a change that does not fit the project.

## Releases

`main` is development. Each minor version has a `release/X.Y` branch, and a fix lands on `main` first and is then backported. Only the latest minor version is supported until 1.0. The details are in `docs/spec.md`, under "Release and distribution".

## Conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

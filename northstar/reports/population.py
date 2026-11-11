"""The accounts a report counts: the ones this person may see that match the request's filters.

A calculation is handed a `Population` and reads only that. It never reads the request's filters and never works out who may see
which account, so those rules live in one place. The protocol is one method, and what stands behind it can change without a
calculation noticing: today every household member sees every live account and no filter is accepted yet, so the population is all
live accounts. Filtering arrives with the filter capabilities, which supply a population built from the conditions on the same
read connection.
"""

import sqlite3
from typing import Protocol


class Population(Protocol):
    def account_ids(self) -> tuple[int, ...]:
        """The ids of the accounts to count, sorted and without repeats."""
        ...


class FixedPopulation:
    """A population of exactly these accounts. What tests use, and what the engine builds from a list of ids."""

    def __init__(self, ids):
        checked = []
        for account_id in ids:
            if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id < 1:
                raise ValueError("An account id is a whole number of 1 or more.")
            checked.append(account_id)
        self._ids = tuple(sorted(set(checked)))

    def account_ids(self) -> tuple[int, ...]:
        return self._ids


def visible_accounts(conn: sqlite3.Connection, user) -> Population:
    """Every live account (a deleted account is in no view), for any signed-in person: a household trusts its own members, so there is
    no per-person visibility of accounts. `user` is here so a rule that narrows it has one place to go."""
    return FixedPopulation(row[0] for row in conn.execute("SELECT id FROM live_accounts ORDER BY id"))

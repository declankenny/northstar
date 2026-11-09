-- northstar: rebuild
-- An account's class is its type's class, so it is no longer stored on the account (issue 181). A second copy of a fact the
-- type already holds had to be kept in step by a composite foreign key from accounts (type_id, class_id) to
-- account_types (id, class_id). Both go: accounts loses class_id and points at its type alone, and account_types loses the
-- UNIQUE (id, class_id) that only that key needed. Behaviour does not change. Run with foreign keys off because both tables
-- are rebuilt: the runner checks the foreign keys, the integrity and that every index, view and trigger survives before it
-- commits.
--
-- The rule the composite key also enforced, that the class of a type cannot change while an account uses it (it would
-- reclassify every one of its accounts, and rewrite net worth for every past date they cover), is now a trigger on
-- account_types. Deleted accounts count: they keep their type so that restoring one is possible.
--
-- That trigger reads accounts, so it is in the way of a rebuild of accounts in the same way the views are (SQLite cannot
-- rename a table while a view or a trigger refers to a table that is missing for a moment): a later rebuild of accounts
-- drops it first, with the views, and creates it again afterwards. The runner's guard checks that it came back.

-- Rebuilding a table forgets how far its AUTOINCREMENT counter had got, so a deleted type's id could be given to a new one.
-- Keep the counters and put them back.
CREATE TEMP TABLE kept_sequence AS
    SELECT name, seq FROM sqlite_sequence WHERE name IN ('account_types', 'accounts');

-- Views first: SQLite cannot rename a table while a view refers to it. account_days reads live_accounts, and uses the
-- class, which it now gets through the type.
DROP VIEW account_days;
DROP VIEW live_balances;
DROP VIEW live_accounts;

CREATE TABLE account_types_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    class_id         INTEGER NOT NULL REFERENCES account_classes (id),
    stale_after_days INTEGER NOT NULL CHECK (stale_after_days >= 1),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by       INTEGER NOT NULL REFERENCES users (id),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by       INTEGER NOT NULL REFERENCES users (id)
);
INSERT INTO account_types_new (id, name, class_id, stale_after_days, created_at, created_by, updated_at, updated_by)
    SELECT id, name, class_id, stale_after_days, created_at, created_by, updated_at, updated_by FROM account_types;
DROP TABLE account_types;
ALTER TABLE account_types_new RENAME TO account_types;

CREATE TABLE accounts_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    -- The type decides the class. A type in use can be neither deleted nor moved to another class.
    type_id     INTEGER NOT NULL REFERENCES account_types (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    -- Set when the account is created and never changed (a trigger refuses it). No default: an insert must choose.
    currency_id INTEGER NOT NULL REFERENCES currencies (id),
    is_open     INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    notes       TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  INTEGER NOT NULL REFERENCES users (id),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by  INTEGER NOT NULL REFERENCES users (id)
);
INSERT INTO accounts_new (id, name, type_id, currency_id, is_open, notes, deleted,
                          created_at, created_by, updated_at, updated_by)
    SELECT id, name, type_id, currency_id, is_open, notes, deleted, created_at, created_by, updated_at, updated_by
    FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE) WHERE deleted = 0;
CREATE TRIGGER accounts_currency_fixed BEFORE UPDATE OF currency_id ON accounts
WHEN NEW.currency_id IS NOT OLD.currency_id
BEGIN
    SELECT RAISE(ABORT, 'The currency of an account cannot be changed.');
END;
-- Reads accounts itself, not live_accounts: a deleted account still holds its type.
CREATE TRIGGER account_types_class_fixed_while_used BEFORE UPDATE OF class_id ON account_types
WHEN NEW.class_id IS NOT OLD.class_id AND EXISTS (SELECT 1 FROM accounts WHERE type_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'The class of a type that accounts use cannot be changed.');
END;

-- The counters, put back where they were (a table with no rows has none, so replace rather than update).
DELETE FROM sqlite_sequence WHERE name IN ('account_types', 'accounts');
INSERT INTO sqlite_sequence (name, seq) SELECT name, seq FROM kept_sequence;
DROP TABLE kept_sequence;

CREATE VIEW live_accounts AS
    SELECT * FROM accounts WHERE deleted = 0;
CREATE VIEW live_balances AS
    SELECT balances.* FROM balances JOIN accounts ON accounts.id = balances.account_id WHERE accounts.deleted = 0;

-- account_days as in migration 0013, with the class read through the type.
CREATE VIEW account_days AS
WITH RECURSIVE
bounds(first_day, last_day) AS (
    SELECT MIN(balances.as_of_date),
           MAX(MAX(balances.as_of_date), COALESCE((SELECT MAX(rate_date) FROM exchange_rates), ''))
    FROM balances JOIN live_accounts ON live_accounts.id = balances.account_id
),
calendar(day) AS (
    SELECT first_day FROM bounds WHERE first_day IS NOT NULL
    UNION ALL
    SELECT date(day, '+1 day') FROM calendar WHERE day < (SELECT last_day FROM bounds)
)
SELECT * FROM (
    SELECT calendar.day AS day, a.id AS account_id, cl.name AS class_name,
           a.currency_id AS currency_id, cur.code AS currency_code, cur.minor_units AS minor_units,
           cur.code <> (SELECT value FROM system_properties WHERE name = 'system.currency') AS converts,
           (SELECT b.amount_cents FROM balances b
             WHERE b.account_id = a.id AND b.as_of_date <= calendar.day
             ORDER BY b.as_of_date DESC LIMIT 1) AS amount,
           (SELECT r.rate FROM exchange_rates r
             WHERE r.currency_id = a.currency_id AND r.rate_date <= calendar.day
             ORDER BY r.rate_date DESC LIMIT 1) AS rate
    FROM calendar
    CROSS JOIN live_accounts a
    JOIN account_types t ON t.id = a.type_id
    JOIN account_classes cl ON cl.id = t.class_id
    JOIN currencies cur ON cur.id = a.currency_id
) WHERE amount IS NOT NULL;

-- Class changes are no longer logged on the account: the type is, and it decides the class.
DELETE FROM sys_audited_fields WHERE tablename = 'accounts' AND fieldname = 'class_id';

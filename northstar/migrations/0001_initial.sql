-- Initial schema. See docs/spec.md, "Data model".
-- Timestamps are UTC text. Dates (as_of_date) are calendar dates, YYYY-MM-DD, no timezone.
-- Money is integer cents.

CREATE TABLE account_classes (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Exactly two rows, never edited in the app.
INSERT INTO account_classes (id, name) VALUES (1, 'Asset'), (2, 'Liability');

CREATE TABLE account_types (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    class_id         INTEGER NOT NULL REFERENCES account_classes (id),
    stale_after_days INTEGER NOT NULL CHECK (stale_after_days >= 1),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Lets accounts point at the (type, class) pair, so a type must match the account's class.
    UNIQUE (id, class_id)
);

-- Starting types. Asset = class 1, Liability = class 2.
INSERT INTO account_types (name, class_id, stale_after_days) VALUES
    ('Checking',         1, 35),
    ('Savings',          1, 35),
    ('Brokerage',        1, 35),
    ('Retirement',       1, 35),
    ('Other investment', 1, 35),
    ('Real estate',      1, 365),
    ('Vehicle',          1, 365),
    ('Other asset',      1, 35),
    ('Credit card',      2, 35),
    ('Loan',             2, 35),
    ('Mortgage',         2, 35),
    ('Other liability',  2, 35);

CREATE TABLE accounts (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    class_id   INTEGER NOT NULL REFERENCES account_classes (id),
    type_id    INTEGER NOT NULL,
    is_open    INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- The type must belong to the account's class. RESTRICT also blocks deleting a type in use
    -- and changing the class of a type in use.
    FOREIGN KEY (type_id, class_id) REFERENCES account_types (id, class_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE balances (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    as_of_date   TEXT NOT NULL CHECK (date(as_of_date) IS as_of_date),
    amount_cents INTEGER NOT NULL,
    note         TEXT,
    source       TEXT NOT NULL DEFAULT 'manual',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (account_id, as_of_date)
);

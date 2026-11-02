-- northstar: rebuild
-- Audit columns, stable ids and the system user. See docs/spec.md, "Data model", and docs/design/v0.2-db-schema.
-- Run by the migration runner with foreign keys off, because it drops and recreates the tables that point at each
-- other. The runner checks the foreign keys, the integrity and that every index survives before it commits.
--
-- Every table the application owns (all but the sys_ tables) gets AUTOINCREMENT, so a deleted id is never reused, and
-- the four audit columns: created_at, created_by, updated_at, updated_by. The author columns are real foreign keys to
-- users. Existing rows are authored by the system user, a row in users that nobody can sign in as.

-- The system user's id: the next free one. Code finds it by is_system, never by this number.
CREATE TEMP TABLE system_user AS SELECT COALESCE(MAX(id), 0) + 1 AS id FROM users;

CREATE TABLE users_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    theme         TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('light', 'dark')),
    -- The row that authors seeded data, this migration's backfill and command line actions. Exactly one.
    is_system     INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by    INTEGER NOT NULL REFERENCES users (id),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by    INTEGER NOT NULL REFERENCES users (id)
);
INSERT INTO users_new (id, email, display_name, password_hash, is_admin, theme, created_at, created_by, updated_at, updated_by)
    SELECT id, email, display_name, password_hash, is_admin, theme, created_at,
           (SELECT id FROM system_user), created_at, (SELECT id FROM system_user)
    FROM users;
-- The hash is not a well-formed hash, so no password verifies against it. Sign-in also refuses the row by its flag.
INSERT INTO users_new (id, email, display_name, password_hash, is_system, created_by, updated_by)
    SELECT id, 'system@northstar.invalid', 'System', '!', 1, id, id FROM system_user;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
CREATE UNIQUE INDEX users_one_system ON users (is_system) WHERE is_system = 1;

CREATE TABLE account_classes_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id)
);
INSERT INTO account_classes_new (id, name, created_by, updated_by)
    SELECT id, name, (SELECT id FROM system_user), (SELECT id FROM system_user) FROM account_classes;
DROP TABLE account_classes;
ALTER TABLE account_classes_new RENAME TO account_classes;

CREATE TABLE account_types_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    class_id         INTEGER NOT NULL REFERENCES account_classes (id),
    stale_after_days INTEGER NOT NULL CHECK (stale_after_days >= 1),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by       INTEGER NOT NULL REFERENCES users (id),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by       INTEGER NOT NULL REFERENCES users (id),
    -- Lets accounts point at the (type, class) pair, so a type must match the account's class.
    UNIQUE (id, class_id)
);
INSERT INTO account_types_new (id, name, class_id, stale_after_days, created_at, created_by, updated_at, updated_by)
    SELECT id, name, class_id, stale_after_days, created_at, (SELECT id FROM system_user), created_at,
           (SELECT id FROM system_user)
    FROM account_types;
DROP TABLE account_types;
ALTER TABLE account_types_new RENAME TO account_types;

CREATE TABLE accounts_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    class_id   INTEGER NOT NULL REFERENCES account_classes (id),
    type_id    INTEGER NOT NULL,
    is_open    INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id),
    -- The type must belong to the account's class. RESTRICT also blocks deleting a type in use
    -- and changing the class of a type in use.
    FOREIGN KEY (type_id, class_id) REFERENCES account_types (id, class_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
INSERT INTO accounts_new (id, name, class_id, type_id, is_open, notes, created_at, created_by, updated_at, updated_by)
    SELECT id, name, class_id, type_id, is_open, notes, created_at, (SELECT id FROM system_user), created_at,
           (SELECT id FROM system_user)
    FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE);

CREATE TABLE balances_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    as_of_date   TEXT NOT NULL CHECK (date(as_of_date) IS as_of_date),
    amount_cents INTEGER NOT NULL,
    note         TEXT,
    source       TEXT NOT NULL DEFAULT 'manual',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by   INTEGER NOT NULL REFERENCES users (id),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by   INTEGER NOT NULL REFERENCES users (id),
    UNIQUE (account_id, as_of_date)
);
INSERT INTO balances_new (id, account_id, as_of_date, amount_cents, note, source, created_at, created_by, updated_at, updated_by)
    SELECT id, account_id, as_of_date, amount_cents, note, source, created_at, (SELECT id FROM system_user), updated_at,
           (SELECT id FROM system_user)
    FROM balances;
DROP TABLE balances;
ALTER TABLE balances_new RENAME TO balances;

DROP TABLE system_user;

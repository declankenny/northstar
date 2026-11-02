-- The change log. See docs/spec.md, "Change log", and docs/design/v0.2-db-schema (change tracking).
-- One sys_operations row per user action that makes a logged change, and one sys_record_changes row per record it
-- changed, with the logged fields as JSON. sys_audited_fields says which fields are logged. All of it is written by
-- northstar/writer.py, in the same transaction as the change it records. These are sys_ tables: no audit columns, never
-- themselves logged. The JSON columns are checked, so a SQLite built without JSON fails here and not later.

-- The origin of an action. A lookup table rather than a CHECK, so a new kind is one more row and not a rebuild.
CREATE TABLE sys_operation_kinds (
    kind TEXT PRIMARY KEY
);
INSERT INTO sys_operation_kinds (kind) VALUES ('ui_edit'), ('bulk_update'), ('import'), ('undo'), ('cli');

CREATE TABLE sys_operations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,      -- also the version written onto the records it changes
    kind                TEXT NOT NULL REFERENCES sys_operation_kinds (kind),
    user_id             INTEGER NOT NULL REFERENCES users (id), -- the system user for the command line
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Set only on an undo. At most one undo per target; that the target is not itself an undo is checked by the code.
    undoes_operation_id INTEGER REFERENCES sys_operations (id),
    detail              TEXT CHECK (detail IS NULL OR json_valid(detail))
);
CREATE INDEX sys_operations_created_at ON sys_operations (created_at);
CREATE UNIQUE INDEX sys_operations_one_undo ON sys_operations (undoes_operation_id) WHERE undoes_operation_id IS NOT NULL;

CREATE TABLE sys_record_changes (
    id           INTEGER PRIMARY KEY,                           -- orders the changes within an operation
    operation_id INTEGER NOT NULL REFERENCES sys_operations (id),
    tablename    TEXT NOT NULL,
    record_id    INTEGER NOT NULL,                              -- the record's id; no foreign key, the table is polymorphic
    change       TEXT NOT NULL CHECK (change IN ('INSERT', 'UPDATE', 'DELETE')),
    old_json     TEXT CHECK (old_json IS NULL OR json_valid(old_json)),   -- null for INSERT; only what changed for UPDATE
    new_json     TEXT CHECK (new_json IS NULL OR json_valid(new_json)),   -- null for DELETE; only what changed for UPDATE
    -- At most one change to a record per operation. This also serves a lookup by operation.
    UNIQUE (operation_id, tablename, record_id)
);
CREATE INDEX sys_record_changes_record ON sys_record_changes (tablename, record_id, id);

-- Which fields are logged: one row for every column of every table that is not a sys_ table. 0 is for the record's own
-- id, secrets, noise and generated metadata. A test fails if a column has no row, so a new column forces the decision.
CREATE TABLE sys_audited_fields (
    tablename TEXT NOT NULL,
    fieldname TEXT NOT NULL,
    is_logged INTEGER NOT NULL DEFAULT 0 CHECK (is_logged IN (0, 1)),
    PRIMARY KEY (tablename, fieldname)
);
INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('account_classes', 'id', 0),
    ('account_classes', 'name', 1),
    ('account_classes', 'created_at', 1),
    ('account_classes', 'created_by', 1),
    ('account_classes', 'updated_at', 0),
    ('account_classes', 'updated_by', 0),

    ('account_types', 'id', 0),
    ('account_types', 'name', 1),
    ('account_types', 'class_id', 1),
    ('account_types', 'stale_after_days', 1),
    ('account_types', 'created_at', 1),
    ('account_types', 'created_by', 1),
    ('account_types', 'updated_at', 0),
    ('account_types', 'updated_by', 0),

    ('accounts', 'id', 0),
    ('accounts', 'name', 1),
    ('accounts', 'class_id', 1),
    ('accounts', 'type_id', 1),
    ('accounts', 'is_open', 1),
    ('accounts', 'notes', 1),
    ('accounts', 'deleted', 1),
    ('accounts', 'created_at', 1),
    ('accounts', 'created_by', 1),
    ('accounts', 'updated_at', 0),
    ('accounts', 'updated_by', 0),

    ('balances', 'id', 0),
    ('balances', 'account_id', 1),
    ('balances', 'as_of_date', 1),
    ('balances', 'amount_cents', 1),
    ('balances', 'note', 1),
    ('balances', 'source', 1),
    ('balances', 'version', 0),
    ('balances', 'created_at', 1),
    ('balances', 'created_by', 1),
    ('balances', 'updated_at', 0),
    ('balances', 'updated_by', 0),

    ('users', 'id', 0),
    ('users', 'email', 1),
    ('users', 'display_name', 1),
    ('users', 'password_hash', 0),
    ('users', 'is_admin', 1),
    ('users', 'theme', 0),
    ('users', 'is_system', 0),
    ('users', 'deleted', 1),
    ('users', 'created_at', 1),
    ('users', 'created_by', 1),
    ('users', 'updated_at', 0),
    ('users', 'updated_by', 0);

-- The id of the operation that last wrote the balance. 0 for balances that existed before the log, which is below every
-- operation id. Generated metadata: never a business change, and not logged.
ALTER TABLE balances ADD COLUMN version INTEGER NOT NULL DEFAULT 0;

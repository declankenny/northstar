-- The columns a person chose for a list (the list framework, #187), saved beside their page size in user_list_prefs.
-- `columns` is a JSON list of field keys in the order they are shown; NULL means the list's own default columns.
-- A person can now choose columns without having chosen a page size (and the other way round), so `page_size` may be NULL too, which
-- takes the table to be rebuilt: SQLite cannot drop a NOT NULL. Nothing refers to this table, so the rebuild touches nothing else.
-- Like the page size, the columns are not a logged field, so changing them leaves no operation in the change log.

CREATE TABLE user_list_prefs_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    list_key   TEXT NOT NULL CHECK (length(list_key) BETWEEN 1 AND 100),
    page_size  INTEGER CHECK (page_size IN (10, 25, 50, 100)),
    columns    TEXT CHECK (columns IS NULL OR (json_valid(columns) AND json_type(columns) = 'array' AND length(columns) <= 8000)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id),
    UNIQUE (user_id, list_key)
);
INSERT INTO user_list_prefs_new (id, user_id, list_key, page_size, created_at, created_by, updated_at, updated_by)
    SELECT id, user_id, list_key, page_size, created_at, created_by, updated_at, updated_by FROM user_list_prefs;
DROP TABLE user_list_prefs;
ALTER TABLE user_list_prefs_new RENAME TO user_list_prefs;

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES ('user_list_prefs', 'columns', 0);

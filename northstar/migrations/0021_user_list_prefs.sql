-- A person's choices for the lists (the list framework, #185): how many rows a page shows, for each list. Step 4 adds the columns
-- they chose. It is a household table with audit columns like the other per-person settings, and the page size is not a logged
-- field (the way a theme is not), so changing it leaves no operation in the change log: only the row's first creation does.
-- One row for each person and list; a list that has none uses its own default.

CREATE TABLE user_list_prefs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    list_key   TEXT NOT NULL CHECK (length(list_key) BETWEEN 1 AND 100),
    page_size  INTEGER NOT NULL CHECK (page_size IN (10, 25, 50, 100)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id),
    UNIQUE (user_id, list_key)
);

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('user_list_prefs', 'id', 0),
    ('user_list_prefs', 'user_id', 1),
    ('user_list_prefs', 'list_key', 1),
    ('user_list_prefs', 'page_size', 0),
    ('user_list_prefs', 'created_at', 1),
    ('user_list_prefs', 'created_by', 1),
    ('user_list_prefs', 'updated_at', 0),
    ('user_list_prefs', 'updated_by', 0);

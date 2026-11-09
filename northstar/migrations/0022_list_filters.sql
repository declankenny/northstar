-- Saved filters for the lists (the list framework, #186). A saved filter is a name and the conditions of a filter, as JSON the list engine
-- validates when it is saved and again when it is used, for one list. A person's own are private to them. A filter with no owner is
-- shared: every person who can see the list sees it, and only an admin makes, changes or removes it. It is a household table with
-- audit columns, and every change to a filter is logged, because a shared filter is configuration that admins change.
--
-- One person has at most one default filter for a list, and a list has at most one shared default: a single partial unique
-- index says both, because a shared filter's owner counts as 0 (no user has that id). A list opens with the person's own default, else
-- the shared one, else with no filter. Names are unique for one owner (or among the shared ones) and one list, ignoring ASCII case; a
-- private filter may have the same name as a shared one. The conditions are never SQL, and a condition that names a column the list
-- no longer offers is skipped when the filter is applied.

CREATE TABLE list_filters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER REFERENCES users (id),
    list_key   TEXT NOT NULL CHECK (length(list_key) BETWEEN 1 AND 100),
    name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    conditions TEXT NOT NULL CHECK (json_valid(conditions) AND json_type(conditions) = 'array' AND length(conditions) <= 20000),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users (id),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by INTEGER NOT NULL REFERENCES users (id)
);

CREATE UNIQUE INDEX list_filters_name_unique ON list_filters (COALESCE(owner_id, 0), list_key, name COLLATE NOCASE);
CREATE UNIQUE INDEX list_filters_one_default ON list_filters (COALESCE(owner_id, 0), list_key) WHERE is_default = 1;

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('list_filters', 'id', 0),
    ('list_filters', 'owner_id', 1),
    ('list_filters', 'list_key', 1),
    ('list_filters', 'name', 1),
    ('list_filters', 'conditions', 1),
    ('list_filters', 'is_default', 1),
    ('list_filters', 'created_at', 1),
    ('list_filters', 'created_by', 1),
    ('list_filters', 'updated_at', 0),
    ('list_filters', 'updated_by', 0);

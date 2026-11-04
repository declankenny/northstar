-- System properties. See docs/design/system-properties/design.md.
-- The settings that belong to the whole installation, as named, typed text values. `system_properties` is an ordinary
-- household table (audit columns, logged), because admins change its values. The three `ref_` tables are loaded here
-- and never written at run time: no audit columns, not logged, and the writer refuses them.

CREATE TABLE ref_property_data_types (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO ref_property_data_types (name) VALUES ('String'), ('Integer'), ('Lookup');

CREATE TABLE system_properties (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Lowercase dotted segments, at least two, each starting with a letter: currency.exchangerate.staleness_days.
    -- The first segment is the group the admin screen lists the property under.
    name         TEXT NOT NULL UNIQUE CHECK (
        name NOT GLOB '*[^a-z0-9_.]*' AND name GLOB '*.*' AND name NOT GLOB '.*' AND name NOT GLOB '*.'
        AND name NOT GLOB '*..*' AND name NOT GLOB '[^a-z]*' AND name NOT GLOB '*.[^a-z]*'),
    data_type_id INTEGER NOT NULL REFERENCES ref_property_data_types (id),
    -- Always text. NULL means unset. Empty text is never a value.
    value        TEXT CHECK (value IS NULL OR length(value) BETWEEN 1 AND 256),
    -- Whether the application may set the value back to unset. A migration may still create a property unset.
    allow_null   INTEGER NOT NULL CHECK (allow_null IN (0, 1)),
    -- Says what the setting does and what it accepts. Shown beside the name on the admin screen.
    hint         TEXT NOT NULL CHECK (length(hint) BETWEEN 1 AND 256),
    read_only    INTEGER NOT NULL DEFAULT 0 CHECK (read_only IN (0, 1)),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by   INTEGER NOT NULL REFERENCES users (id),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by   INTEGER NOT NULL REFERENCES users (id)
);

-- The allowed values of a property whose type is Lookup: a short list. At most 20 per property, which a test checks.
CREATE TABLE ref_property_lookups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES system_properties (id) ON DELETE CASCADE,
    value       TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 256),   -- what is stored in the property's value
    label       TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 256),   -- what a person sees
    UNIQUE (property_id, value)
);

-- The feature validations that run for a property after its data type check, in position order. `validator` is the name
-- of a function in northstar/system_properties.py (VALIDATORS), never an expression. A property with no rows is
-- checked by its data type alone.
CREATE TABLE ref_property_validators (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES system_properties (id) ON DELETE CASCADE,
    validator   TEXT NOT NULL CHECK (length(validator) > 0),
    position    INTEGER NOT NULL CHECK (position >= 1),
    UNIQUE (property_id, validator),
    UNIQUE (property_id, position)
);

-- The first properties. Authored by the system user, like every seeded row.
INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT p.name, (SELECT id FROM ref_property_data_types WHERE name = p.type), p.value, 0, p.hint,
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1)
FROM (
    SELECT 'ui.theme.default' AS name, 'Lookup' AS type, 'dark' AS value,
           'The theme every new user starts with. Each user can change theirs.' AS hint
    UNION ALL SELECT 'balance.stale', 'Integer', '35',
           'Days before an account is flagged stale, as filled in for a new account type. Enter 1 or more.'
    UNION ALL SELECT 'system.currency', 'String', 'USD',
           'The currency code amounts are shown in: three capital letters, such as USD.'
) AS p;

INSERT INTO ref_property_lookups (property_id, value, label)
SELECT (SELECT id FROM system_properties WHERE name = 'ui.theme.default'), v.value, v.label
FROM (SELECT 'light' AS value, 'Light' AS label UNION ALL SELECT 'dark', 'Dark') AS v;

INSERT INTO ref_property_validators (property_id, validator, position)
SELECT (SELECT id FROM system_properties WHERE name = v.name), v.validator, 1
FROM (
    SELECT 'balance.stale' AS name, 'positive_integer' AS validator
    UNION ALL SELECT 'system.currency', 'three_capital_letters'
) AS v;

-- Which fields are logged. The id and the two columns that say who last changed it and when are not.
INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('system_properties', 'id', 0),
    ('system_properties', 'name', 1),
    ('system_properties', 'data_type_id', 1),
    ('system_properties', 'value', 1),
    ('system_properties', 'allow_null', 1),
    ('system_properties', 'hint', 1),
    ('system_properties', 'read_only', 1),
    ('system_properties', 'created_at', 1),
    ('system_properties', 'created_by', 1),
    ('system_properties', 'updated_at', 0),
    ('system_properties', 'updated_by', 0);

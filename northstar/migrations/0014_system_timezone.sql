-- The installation's time zone: an IANA name such as America/Chicago, the one source of what "today" is. It starts empty. At
-- startup, while it is empty, the application copies the TZ environment variable into it once (see northstar/clock.py), and
-- with neither it uses UTC. The iana_timezone validator checks a name against the zone database. See docs/decisions.md.

INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT 'system.timezone', (SELECT id FROM ref_property_data_types WHERE name = 'String'), NULL, 1,
       'The time zone that decides what today is, as a name such as America/Chicago or Europe/London. Empty means UTC.',
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1);

INSERT INTO ref_property_validators (property_id, validator, position)
    SELECT id, 'iana_timezone', 1 FROM system_properties WHERE name = 'system.timezone';

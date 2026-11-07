-- The daily exchange-rate fetch (#131), the first job of the in-app scheduler. `currency.rate.fetch_time` is its start time, read
-- in the installation's time zone: a Time, 18:00 until an admin changes it, and empty switches the fetch off. Rates the scheduler
-- writes are an operation of kind `scheduled`, made by the system user. See docs/design/currency/design.md.

INSERT INTO sys_operation_kinds (kind) VALUES ('scheduled');

INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT 'currency.rate.fetch_time', (SELECT id FROM ref_property_data_types WHERE name = 'Time'), '18:00', 1,
       'The time of day Northstar fetches exchange rates from the provider, in the time zone set in system.timezone, as 24-hour HH:MM. Empty turns automatic fetching off.',
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1);

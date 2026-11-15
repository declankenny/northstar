-- Retention of deleted data and the nightly cleanup (history and recovery, step 3: #269, docs/design/history-and-recovery).
--
-- `data.deleted.retention_days` is how long a deleted account or an individually deleted balance stays recoverable, counted from its
-- deletion. `data.deleted.cleanup_time` is the start time of the daily cleanup job, read in the installation's time zone: a Time,
-- 03:00 until an admin changes it, and empty switches the cleanup off. Neither property is read by anything but the job.
--
-- `purge` is the kind of operation the cleanup makes. Its header says which record it removed and nothing that was in it.

INSERT INTO sys_operation_kinds (kind) VALUES ('purge');

INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT p.name, (SELECT id FROM ref_property_data_types WHERE name = p.type), p.value, p.allow_null, p.hint,
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1)
FROM (
    SELECT 'data.deleted.retention_days' AS name, 'Integer' AS type, '90' AS value, 0 AS allow_null,
           'How many days a deleted account or balance can be recovered. After that the nightly cleanup removes it for good, with its history.' AS hint
    UNION ALL
    SELECT 'data.deleted.cleanup_time', 'Time', '03:00', 1,
           'The time of day Northstar permanently removes deleted data that has passed its retention period, in the time zone set in system.timezone, as 24-hour HH:MM. Empty turns the cleanup off.'
) AS p;

INSERT INTO ref_property_validators (property_id, validator, position)
    SELECT id, 'positive_integer', 1 FROM system_properties WHERE name = 'data.deleted.retention_days';

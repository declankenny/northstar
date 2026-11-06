-- The system property `balance.stale` becomes `system.balance.stale_days`: the unit is in the name, and the first segment is the
-- group the settings screen lists it under. The row keeps its id, so its value, its validators and its change history stay with
-- it. No release has carried the old name. See docs/decisions.md.

UPDATE system_properties SET name = 'system.balance.stale_days' WHERE name = 'balance.stale';

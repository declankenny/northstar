-- The Accounts list (issue 190, step 8).
--
-- 1. account_summaries (migration 0024) now carries the columns of the account too. The list framework follows an account's
--    relations (its type, its currency, who made it) from the foreign keys of the table a view is based on, and leaves out a
--    relation whose column the view does not have, so a view of computed columns alone could not be a list of accounts. The
--    computed columns are unchanged and come after the account's own; `a.*` is the live account, so a deleted one is still absent.
--    Migration 0024 is not edited because a database may already have it.
-- 2. The shared default filter "Open accounts" (Open is Yes). It is an ordinary shared filter, so an admin can rename it, change it
--    or delete it, and a person's own default or a cleared filter takes its place for them (see migration 0022).
--
-- A later rebuild of accounts or balances must drop account_summaries first, as 0024 says, and create it again afterwards.

DROP VIEW account_summaries;

CREATE VIEW account_summaries AS
SELECT a.*,
       (SELECT COUNT(*) FROM live_balances c WHERE c.account_id = a.id) AS balance_count,
       lb.as_of_date AS last_date,
       lb.amount_cents AS last_cents,
       v.reporting_value,
       v.reporting_scale,
       v.reporting_unit,
       CAST(julianday(northstar_today()) - julianday(lb.as_of_date) AS INTEGER) AS days_since,
       CASE WHEN a.is_open = 0 THEN 0
            WHEN lb.as_of_date IS NULL THEN 1
            WHEN julianday(northstar_today()) - julianday(lb.as_of_date) > t.stale_after_days THEN 1
            ELSE 0 END AS is_stale
FROM live_accounts a
JOIN account_types t ON t.id = a.type_id
LEFT JOIN last_balances lb ON lb.account_id = a.id
LEFT JOIN live_balance_values v ON v.id = lb.id;

INSERT INTO list_filters (owner_id, list_key, name, conditions, is_default, created_by, updated_by)
VALUES (NULL, 'accounts', 'Open accounts', '[{"field":"is_open","operator":"is_yes"}]', 1,
        (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1));

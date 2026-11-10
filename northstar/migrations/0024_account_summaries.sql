-- Two views for the Accounts list (issue 190, the lists framework): an account's last balance, and one row of figures for each
-- live account. Both read the live views, so a deleted account and its balances never appear in them.
--
-- last_balances is each live account's newest balance, with the columns of live_balances. An account with no balance has no
-- row. There is one balance per account and date, so "newest" is never a tie. Anything that needs an account's last balance
-- reads this view instead of ordering and limiting in its own query.
--
-- account_summaries holds the computed columns of an account, one row for each live account, keyed by id. It holds nothing
-- that a relation of the account already gives (its class, type, currency, name, notes or whether it is open); a list reads
-- those through the account itself. The last balance and its date come from last_balances, and reporting_value from
-- live_balance_values for that same balance, so it is the value in the system currency by the rule in docs/spec.md
-- ("Conversion"), empty when there is no rate yet. last_cents is in the account's own currency, which a list reads through
-- the account's currency relation; reporting_scale and reporting_unit are the system currency's, as in live_balance_values.
--
-- days_since and is_stale are the rules of northstar/staleness.py written in SQL, for today's date in the installation's
-- time zone, which is the SQL function northstar_today() (northstar/clock.py, registered on every connection the
-- application opens, like northstar_convert for live_balance_values). days_since is empty when there is no balance. An open
-- account is stale when its last balance is older than its type's stale_after_days, or it has none; a closed account never is.
-- A test checks that the view and staleness.py agree.
--
-- Both views call or read views that call SQL functions, so they can only be read through the application's connection. A
-- later rebuild of accounts or balances must drop account_summaries first, then last_balances, with the other views, and
-- create them again afterwards.

CREATE VIEW last_balances AS
SELECT b.*
FROM live_balances b
WHERE NOT EXISTS (SELECT 1 FROM live_balances newer
                   WHERE newer.account_id = b.account_id AND newer.as_of_date > b.as_of_date);

CREATE VIEW account_summaries AS
SELECT a.id,
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

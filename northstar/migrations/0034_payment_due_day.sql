-- A payment due day for a liability account (#258): the day of the month, 1 to 31, that a payment is due.
--
-- Only a due day is stored, never a date, so the data cannot go stale: the next due date is worked out when it is read. The rule is
-- in code (accounts.clean_due_day: liabilities only, a whole number from 1 to 31); the CHECK only keeps a stored value in range.
-- No existing row changes.
--
-- account_summaries (the Accounts list, and the account page's next due date) gets a `next_due` column. A due day beyond a short
-- month's last day falls on the last day of that month. It is this month's due date when that is today or later, otherwise next
-- month's, and it is empty for an account with no due day and for a closed account (the day is kept, and counts again on reopening).
-- `northstar_today()` is today in the installation's zone (see clock.py), so the date and the sorting need nothing else.
--
-- A plain ADD COLUMN is enough for the table: live_accounts reads `accounts.*`. The summary view is made again because it gains a
-- computed column, as migration 0025 says a rebuild must do (drop it first, create it again after).

ALTER TABLE accounts ADD COLUMN due_day INTEGER CHECK (due_day IS NULL OR due_day BETWEEN 1 AND 31);

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES ('accounts', 'due_day', 1);

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
            ELSE 0 END AS is_stale,
       CASE WHEN a.due_day IS NULL OR a.is_open = 0 THEN NULL
            WHEN min(a.due_day, m.last0) >= CAST(strftime('%d', m.today) AS INTEGER)
                 THEN date(m.start0, '+' || (min(a.due_day, m.last0) - 1) || ' days')
            ELSE date(m.start1, '+' || (min(a.due_day, m.last1) - 1) || ' days') END AS next_due
FROM live_accounts a
JOIN account_types t ON t.id = a.type_id
-- today, the first of this month and of next, and the last day of each, worked out once for the whole query
CROSS JOIN (SELECT n.today, n.start0, n.start1,
                   CAST(strftime('%d', date(n.start1, '-1 day')) AS INTEGER) AS last0,
                   CAST(strftime('%d', date(n.start1, '+1 month', '-1 day')) AS INTEGER) AS last1
            FROM (SELECT northstar_today() AS today,
                         date(northstar_today(), 'start of month') AS start0,
                         date(northstar_today(), 'start of month', '+1 month') AS start1) n) m
LEFT JOIN last_balances lb ON lb.account_id = a.id
LEFT JOIN live_balance_values v ON v.id = lb.id;

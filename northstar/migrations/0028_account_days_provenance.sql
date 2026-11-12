-- account_days says which balance and which rate each row used (the position calculation, northstar/positions.py).
--
-- A balance is a recorded fact (an amount and a date); an account's position on a day is its latest balance on or before the day, at the
-- latest rate on or before the day, whatever date the balance has. The view already looked both up and kept the amount and the rate. It
-- now also keeps the balance's id, its date and the rate's date, so a report can show where a figure came from and link to the balance
-- without asking again. The rule and the other columns are unchanged, in the same order, and the rows are the same.
--
-- Each lookup is made once, for the balance and for the rate, and the row is then read by its key. A day on which an account has no
-- balance is still left out, as before. It reads live_accounts and balances, so a later rebuild of either table must drop it first,
-- with the other views, and create it again afterwards.

DROP VIEW account_days;

CREATE VIEW account_days AS
WITH RECURSIVE
bounds(first_day, last_day) AS (
    SELECT MIN(balances.as_of_date),
           MAX(MAX(balances.as_of_date), COALESCE((SELECT MAX(rate_date) FROM exchange_rates), ''))
    FROM balances JOIN live_accounts ON live_accounts.id = balances.account_id
),
calendar(day) AS (
    SELECT first_day FROM bounds WHERE first_day IS NOT NULL
    UNION ALL
    SELECT date(day, '+1 day') FROM calendar WHERE day < (SELECT last_day FROM bounds)
)
SELECT calendar.day AS day, a.id AS account_id, cl.name AS class_name,
       a.currency_id AS currency_id, cur.code AS currency_code, cur.minor_units AS minor_units,
       cur.code <> (SELECT value FROM system_properties WHERE name = 'system.currency') AS converts,
       b.amount_cents AS amount,
       r.rate AS rate,
       b.id AS balance_id,
       b.as_of_date AS balance_date,
       r.rate_date AS rate_date
FROM calendar
CROSS JOIN live_accounts a
JOIN account_types t ON t.id = a.type_id
JOIN account_classes cl ON cl.id = t.class_id
JOIN currencies cur ON cur.id = a.currency_id
JOIN balances b ON b.id = (SELECT x.id FROM balances x
                            WHERE x.account_id = a.id AND x.as_of_date <= calendar.day
                            ORDER BY x.as_of_date DESC LIMIT 1)
LEFT JOIN exchange_rates r ON r.id = (SELECT y.id FROM exchange_rates y
                                       WHERE y.currency_id = a.currency_id AND y.rate_date <= calendar.day
                                       ORDER BY y.rate_date DESC LIMIT 1);

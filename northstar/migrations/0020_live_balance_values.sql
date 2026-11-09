-- The balances of live accounts with each one's value in the system currency (issue 184, the lists framework). A list shows
-- these as plain columns, so sorting and filtering by the converted value is the database's own work.
--
-- reporting_value converts with the latest rate of the account's currency on or before the balance's own date, never a later
-- one, as docs/spec.md ("Conversion") says: it is the system currency's own amount when the account is in the system currency,
-- and empty when there is no rate yet (or no system currency yet), never zero. reporting_scale and reporting_unit are the system
-- currency's decimal places and code, so a page can write the value. The arithmetic is northstar_convert, which is
-- northstar/conversion.py registered on every connection the application opens, so it is the same code net worth runs. A query
-- through this view needs such a connection.
--
-- It reads live_balances, live_accounts and, for the rate, the same subquery as account_days (migration 0019), which is the
-- rule's other place in SQL: a test checks that the two give the same rate. A later rebuild of accounts or balances must drop this
-- view first, with the others, and create it again afterwards.

CREATE VIEW live_balance_values AS
SELECT b.*,
       CASE WHEN cur.code = sys.code THEN b.amount_cents
            ELSE northstar_convert(b.amount_cents, cur.minor_units,
                                   (SELECT r.rate FROM exchange_rates r
                                     WHERE r.currency_id = a.currency_id AND r.rate_date <= b.as_of_date
                                     ORDER BY r.rate_date DESC LIMIT 1),
                                   sys.minor_units) END AS reporting_value,
       sys.minor_units AS reporting_scale,
       sys.code AS reporting_unit
FROM live_balances b
JOIN live_accounts a ON a.id = b.account_id
JOIN currencies cur ON cur.id = a.currency_id
LEFT JOIN (SELECT c.code, c.minor_units FROM currencies c
            WHERE c.code = (SELECT value FROM system_properties WHERE name = 'system.currency')) sys ON 1;

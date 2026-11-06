-- Exchange rates and conversion into the system currency. See docs/design/currency/design.md and the design on issue #130.
--
-- One rate means 1 unit of the currency = `rate` units of the system currency, on the date the rate is for. The rate is text,
-- an exact decimal: SQLite has no decimal type, REAL is floating point, and the conversion is done in Python.

-- Rates are for currencies other than the system currency, and the date they start from is chosen when a currency is first
-- enabled. The system currency has no rates and no start date.
ALTER TABLE currencies ADD COLUMN rates_start TEXT
    CHECK (rates_start IS NULL OR rates_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]');

-- The system currency is always enabled. An existing installation already has its system currency (USD when it has accounts).
UPDATE currencies SET is_enabled = 1
 WHERE code = (SELECT value FROM system_properties WHERE name = 'system.currency');

CREATE TABLE exchange_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    currency_id INTEGER NOT NULL REFERENCES currencies (id),
    -- The calendar date the rate is for, with no timezone.
    rate_date   TEXT NOT NULL CHECK (rate_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    -- Digits and at most one point, with a digit other than zero in it. The service also limits the digits and the size.
    rate        TEXT NOT NULL CHECK (rate GLOB '[0-9]*' AND rate NOT GLOB '*[^0-9.]*' AND rate NOT GLOB '*.*.*'
                                     AND rate NOT GLOB '*.' AND rate GLOB '*[1-9]*' AND length(rate) <= 25),
    -- Who the value came from. A correction by an administrator makes it manual.
    source      TEXT NOT NULL CHECK (source IN ('manual', 'provider')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  INTEGER NOT NULL REFERENCES users (id),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by  INTEGER NOT NULL REFERENCES users (id),
    UNIQUE (currency_id, rate_date)
);

-- A rate is never deleted, and its currency and date never change: a value can be corrected, and nothing else about it.
CREATE TRIGGER exchange_rates_never_deleted BEFORE DELETE ON exchange_rates
BEGIN
    SELECT RAISE(ABORT, 'A rate cannot be deleted.');
END;
CREATE TRIGGER exchange_rates_date_fixed BEFORE UPDATE OF currency_id, rate_date ON exchange_rates
WHEN NEW.currency_id IS NOT OLD.currency_id OR NEW.rate_date IS NOT OLD.rate_date
BEGIN
    SELECT RAISE(ABORT, 'The currency and date of a rate cannot be changed.');
END;

-- One row for every day from the first balance to the newest balance or rate, and for every account that has a balance by that
-- day: the account's latest balance on or before the day, and the latest rate of its currency on or before the day (empty for
-- the system currency, and for a currency with no rate yet). It only looks things up. The conversion, which needs exact decimal
-- arithmetic that SQLite does not have, is done by northstar/networth.py. The calendar stops at the newest date there is data
-- for, because nothing changes after it, so a later day is answered with the last one. It cannot end at today: SQLite's idea of
-- today is UTC, and the application reads the date in one place, clock.today(). It reads live_accounts and the balances table
-- itself, so a deleted account's balances move neither the calendar nor a total.
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
SELECT * FROM (
    SELECT calendar.day AS day, a.id AS account_id, cl.name AS class_name,
           a.currency_id AS currency_id, cur.code AS currency_code, cur.minor_units AS minor_units,
           cur.code <> (SELECT value FROM system_properties WHERE name = 'system.currency') AS converts,
           (SELECT b.amount_cents FROM balances b
             WHERE b.account_id = a.id AND b.as_of_date <= calendar.day
             ORDER BY b.as_of_date DESC LIMIT 1) AS amount,
           (SELECT r.rate FROM exchange_rates r
             WHERE r.currency_id = a.currency_id AND r.rate_date <= calendar.day
             ORDER BY r.rate_date DESC LIMIT 1) AS rate
    FROM calendar
    CROSS JOIN live_accounts a
    JOIN account_classes cl ON cl.id = a.class_id
    JOIN currencies cur ON cur.id = a.currency_id
) WHERE amount IS NOT NULL;

-- A date is a kind of setting: an ISO calendar date, shown and edited in the person's own format.
INSERT INTO ref_property_data_types (name) VALUES ('Date');

INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT p.name, (SELECT id FROM ref_property_data_types WHERE name = p.type), p.value, 0, p.hint,
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1)
FROM (
    SELECT 'currency.rate.stale_days' AS name, 'Integer' AS type, '14' AS value,
           'Days after the newest rate of a currency that has open accounts before its page warns that the rates are stale. Enter 1 or more.' AS hint
    UNION ALL SELECT 'currency.rate.start.default', 'Date', '2000-01-01',
           'The date rates start from, as filled in when a currency is first enabled. Each currency keeps its own date. Changing this does not change them.'
) AS p;

INSERT INTO ref_property_validators (property_id, validator, position)
    SELECT id, 'positive_integer', 1 FROM system_properties WHERE name = 'currency.rate.stale_days';

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('currencies', 'rates_start', 1),
    ('exchange_rates', 'id', 0),
    ('exchange_rates', 'currency_id', 1),
    ('exchange_rates', 'rate_date', 1),
    ('exchange_rates', 'rate', 1),
    ('exchange_rates', 'source', 1),
    ('exchange_rates', 'created_at', 1),
    ('exchange_rates', 'created_by', 1),
    ('exchange_rates', 'updated_at', 0),
    ('exchange_rates', 'updated_by', 0);

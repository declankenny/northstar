-- northstar: rebuild
-- The currency catalog, the currency of an account and the system currency. See docs/design/currency/design.md and
-- docs/spec.md, "Currencies". Run with foreign keys off because accounts is rebuilt: the runner checks the foreign keys,
-- the integrity and that every index, view and trigger survives before it commits.
--
-- `amount_cents` is not renamed: it holds integers in the minor unit of the account's currency (cents for USD, whole yen
-- for JPY, fils for KWD).

CREATE TABLE currencies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The ISO 4217 code.
    code        TEXT NOT NULL UNIQUE CHECK (length(code) = 3 AND code NOT GLOB '*[^A-Z]*'),
    -- ISO's own name, unchanged.
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    -- Digits after the decimal point. ISO also has two codes with four; they are funds and are not in the catalog.
    minor_units INTEGER NOT NULL CHECK (minor_units IN (0, 2, 3)),
    -- Whether new accounts may use the currency. The system currency is usable whatever this says.
    is_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (is_enabled IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  INTEGER NOT NULL REFERENCES users (id),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by  INTEGER NOT NULL REFERENCES users (id)
);

-- A currency is never removed, and its code and precision never change, because that would silently change what every
-- stored balance means. Only is_enabled is ever changed by the application. (The trigger does not look at accounts, so
-- that a later rebuild of accounts need not drop it. A migration that must correct the catalog drops it and creates it again.)
CREATE TRIGGER currencies_never_deleted BEFORE DELETE ON currencies
BEGIN
    SELECT RAISE(ABORT, 'A currency cannot be deleted.');
END;
CREATE TRIGGER currencies_code_and_precision_fixed BEFORE UPDATE OF code, minor_units ON currencies
WHEN NEW.code IS NOT OLD.code OR NEW.minor_units IS NOT OLD.minor_units
BEGIN
    SELECT RAISE(ABORT, 'The code and precision of a currency cannot be changed.');
END;

-- The active ISO 4217 currencies with 0, 2 or 3 minor units, from the SIX "list one" file published 2026-09-17. Funds, metals,
-- units of account and the testing and no-currency codes are not included. Generated from the file, not typed by hand.
INSERT INTO currencies (code, name, minor_units, created_by, updated_by)
WITH v (code, name, minor_units) AS (VALUES
    ('AED', 'UAE Dirham', 2),
    ('AFN', 'Afghani', 2),
    ('ALL', 'Lek', 2),
    ('AMD', 'Armenian Dram', 2),
    ('AOA', 'Kwanza', 2),
    ('ARS', 'Argentine Peso', 2),
    ('AUD', 'Australian Dollar', 2),
    ('AWG', 'Aruban Florin', 2),
    ('AZN', 'Azerbaijan Manat', 2),
    ('BAM', 'Convertible Mark', 2),
    ('BBD', 'Barbados Dollar', 2),
    ('BDT', 'Taka', 2),
    ('BHD', 'Bahraini Dinar', 3),
    ('BIF', 'Burundi Franc', 0),
    ('BMD', 'Bermudian Dollar', 2),
    ('BND', 'Brunei Dollar', 2),
    ('BOB', 'Boliviano', 2),
    ('BRL', 'Brazilian Real', 2),
    ('BSD', 'Bahamian Dollar', 2),
    ('BTN', 'Ngultrum', 2),
    ('BWP', 'Pula', 2),
    ('BYN', 'Belarusian Ruble', 2),
    ('BZD', 'Belize Dollar', 2),
    ('CAD', 'Canadian Dollar', 2),
    ('CDF', 'Congolese Franc', 2),
    ('CHF', 'Swiss Franc', 2),
    ('CLP', 'Chilean Peso', 0),
    ('CNY', 'Yuan Renminbi', 2),
    ('COP', 'Colombian Peso', 2),
    ('CRC', 'Costa Rican Colon', 2),
    ('CUP', 'Cuban Peso', 2),
    ('CVE', 'Cabo Verde Escudo', 2),
    ('CZK', 'Czech Koruna', 2),
    ('DJF', 'Djibouti Franc', 0),
    ('DKK', 'Danish Krone', 2),
    ('DOP', 'Dominican Peso', 2),
    ('DZD', 'Algerian Dinar', 2),
    ('EGP', 'Egyptian Pound', 2),
    ('ERN', 'Nakfa', 2),
    ('ETB', 'Ethiopian Birr', 2),
    ('EUR', 'Euro', 2),
    ('FJD', 'Fiji Dollar', 2),
    ('FKP', 'Falkland Islands Pound', 2),
    ('GBP', 'Pound Sterling', 2),
    ('GEL', 'Lari', 2),
    ('GHS', 'Ghana Cedi', 2),
    ('GIP', 'Gibraltar Pound', 2),
    ('GMD', 'Dalasi', 2),
    ('GNF', 'Guinean Franc', 0),
    ('GTQ', 'Quetzal', 2),
    ('GYD', 'Guyana Dollar', 2),
    ('HKD', 'Hong Kong Dollar', 2),
    ('HNL', 'Lempira', 2),
    ('HTG', 'Gourde', 2),
    ('HUF', 'Forint', 2),
    ('IDR', 'Rupiah', 2),
    ('ILS', 'New Israeli Sheqel', 2),
    ('INR', 'Indian Rupee', 2),
    ('IQD', 'Iraqi Dinar', 3),
    ('IRR', 'Iranian Rial', 2),
    ('ISK', 'Iceland Krona', 0),
    ('JMD', 'Jamaican Dollar', 2),
    ('JOD', 'Jordanian Dinar', 3),
    ('JPY', 'Yen', 0),
    ('KES', 'Kenyan Shilling', 2),
    ('KGS', 'Som', 2),
    ('KHR', 'Riel', 2),
    ('KMF', 'Comorian Franc', 0),
    ('KPW', 'North Korean Won', 2),
    ('KRW', 'Won', 0),
    ('KWD', 'Kuwaiti Dinar', 3),
    ('KYD', 'Cayman Islands Dollar', 2),
    ('KZT', 'Tenge', 2),
    ('LAK', 'Lao Kip', 2),
    ('LBP', 'Lebanese Pound', 2),
    ('LKR', 'Sri Lanka Rupee', 2),
    ('LRD', 'Liberian Dollar', 2),
    ('LSL', 'Loti', 2),
    ('LYD', 'Libyan Dinar', 3),
    ('MAD', 'Moroccan Dirham', 2),
    ('MDL', 'Moldovan Leu', 2),
    ('MGA', 'Malagasy Ariary', 2),
    ('MKD', 'Denar', 2),
    ('MMK', 'Kyat', 2),
    ('MNT', 'Tugrik', 2),
    ('MOP', 'Pataca', 2),
    ('MRU', 'Ouguiya', 2),
    ('MUR', 'Mauritius Rupee', 2),
    ('MVR', 'Rufiyaa', 2),
    ('MWK', 'Malawi Kwacha', 2),
    ('MXN', 'Mexican Peso', 2),
    ('MYR', 'Malaysian Ringgit', 2),
    ('MZN', 'Mozambique Metical', 2),
    ('NAD', 'Namibia Dollar', 2),
    ('NGN', 'Naira', 2),
    ('NIO', 'Cordoba Oro', 2),
    ('NOK', 'Norwegian Krone', 2),
    ('NPR', 'Nepalese Rupee', 2),
    ('NZD', 'New Zealand Dollar', 2),
    ('OMR', 'Rial Omani', 3),
    ('PAB', 'Balboa', 2),
    ('PEN', 'Sol', 2),
    ('PGK', 'Kina', 2),
    ('PHP', 'Philippine Peso', 2),
    ('PKR', 'Pakistan Rupee', 2),
    ('PLN', 'Zloty', 2),
    ('PYG', 'Guarani', 0),
    ('QAR', 'Qatari Rial', 2),
    ('RON', 'Romanian Leu', 2),
    ('RSD', 'Serbian Dinar', 2),
    ('RUB', 'Russian Ruble', 2),
    ('RWF', 'Rwanda Franc', 0),
    ('SAR', 'Saudi Riyal', 2),
    ('SBD', 'Solomon Islands Dollar', 2),
    ('SCR', 'Seychelles Rupee', 2),
    ('SDG', 'Sudanese Pound', 2),
    ('SEK', 'Swedish Krona', 2),
    ('SGD', 'Singapore Dollar', 2),
    ('SHP', 'Saint Helena Pound', 2),
    ('SLE', 'Leone', 2),
    ('SOS', 'Somali Shilling', 2),
    ('SRD', 'Surinam Dollar', 2),
    ('SSP', 'South Sudanese Pound', 2),
    ('STN', 'Dobra', 2),
    ('SVC', 'El Salvador Colon', 2),
    ('SYP', 'Syrian Pound', 2),
    ('SZL', 'Lilangeni', 2),
    ('THB', 'Baht', 2),
    ('TJS', 'Somoni', 2),
    ('TMT', 'Turkmenistan New Manat', 2),
    ('TND', 'Tunisian Dinar', 3),
    ('TOP', 'Pa’anga', 2),
    ('TRY', 'Turkish Lira', 2),
    ('TTD', 'Trinidad and Tobago Dollar', 2),
    ('TWD', 'New Taiwan Dollar', 2),
    ('TZS', 'Tanzanian Shilling', 2),
    ('UAH', 'Hryvnia', 2),
    ('UGX', 'Uganda Shilling', 0),
    ('USD', 'US Dollar', 2),
    ('UYU', 'Peso Uruguayo', 2),
    ('UZS', 'Uzbekistan Sum', 2),
    ('VED', 'Bolívar Soberano', 2),
    ('VES', 'Bolívar Soberano', 2),
    ('VND', 'Dong', 0),
    ('VUV', 'Vatu', 0),
    ('WST', 'Tala', 2),
    ('XAF', 'CFA Franc BEAC', 0),
    ('XCD', 'East Caribbean Dollar', 2),
    ('XCG', 'Caribbean Guilder', 2),
    ('XOF', 'CFA Franc BCEAO', 0),
    ('XPF', 'CFP Franc', 0),
    ('YER', 'Yemeni Rial', 2),
    ('ZAR', 'Rand', 2),
    ('ZMW', 'Zambian Kwacha', 2),
    ('ZWG', 'Zimbabwe Gold', 2)
)
SELECT v.code, v.name, v.minor_units, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1)
FROM v ORDER BY v.code;

-- Rebuild accounts with its currency. Views first: SQLite cannot rename a table while a view refers to it.
DROP VIEW live_balances;
DROP VIEW live_accounts;

CREATE TABLE accounts_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    class_id    INTEGER NOT NULL REFERENCES account_classes (id),
    type_id     INTEGER NOT NULL,
    -- Set when the account is created and never changed (a trigger refuses it). No default: an insert must choose.
    currency_id INTEGER NOT NULL REFERENCES currencies (id),
    is_open     INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    notes       TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    created_by  INTEGER NOT NULL REFERENCES users (id),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_by  INTEGER NOT NULL REFERENCES users (id),
    FOREIGN KEY (type_id, class_id) REFERENCES account_types (id, class_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
-- Every existing amount is a US dollar amount, so every existing account is in US dollars.
INSERT INTO accounts_new (id, name, class_id, type_id, currency_id, is_open, notes, deleted,
                          created_at, created_by, updated_at, updated_by)
    SELECT id, name, class_id, type_id, (SELECT id FROM currencies WHERE code = 'USD'), is_open, notes, deleted,
           created_at, created_by, updated_at, updated_by
    FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE) WHERE deleted = 0;
CREATE TRIGGER accounts_currency_fixed BEFORE UPDATE OF currency_id ON accounts
WHEN NEW.currency_id IS NOT OLD.currency_id
BEGIN
    SELECT RAISE(ABORT, 'The currency of an account cannot be changed.');
END;

CREATE VIEW live_accounts AS
    SELECT * FROM accounts WHERE deleted = 0;
CREATE VIEW live_balances AS
    SELECT balances.* FROM balances JOIN accounts ON accounts.id = balances.account_id WHERE accounts.deleted = 0;

-- The system currency. An installation that already has an account (a deleted one counts: it keeps its currency) is in US
-- dollars and the setting is locked. One with no account has it unset, and an administrator sets it before the first
-- account can be created. The setting is checked against the catalog and locked by the validator below.
UPDATE system_properties
   SET value = CASE WHEN EXISTS (SELECT 1 FROM accounts) THEN 'USD' ELSE NULL END,
       read_only = CASE WHEN EXISTS (SELECT 1 FROM accounts) THEN 1 ELSE 0 END,
       hint = 'The currency every total is shown in. Choose it once: it is locked as soon as it is saved. Search the list by code or name.'
 WHERE name = 'system.currency';
DELETE FROM ref_property_validators WHERE validator = 'three_capital_letters';
INSERT INTO ref_property_validators (property_id, validator, position)
    SELECT id, 'catalog_currency', 1 FROM system_properties WHERE name = 'system.currency';

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES
    ('currencies', 'id', 0),
    ('currencies', 'code', 1),
    ('currencies', 'name', 1),
    ('currencies', 'minor_units', 1),
    ('currencies', 'is_enabled', 1),
    ('currencies', 'created_at', 1),
    ('currencies', 'created_by', 1),
    ('currencies', 'updated_at', 0),
    ('currencies', 'updated_by', 0),
    ('accounts', 'currency_id', 1);

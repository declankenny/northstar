-- Unique account names. See docs/spec.md, "Data model", and docs/decisions.md.
-- Names are compared with SQLite's NOCASE (ASCII case only), like account_types.name and users.email, and are trimmed
-- by the application before they are stored. The index covers open and closed accounts alike.

-- Names were trimmed on write, so this does not rewrite them. If one is not, stop and roll back rather than guess.
CREATE TEMP TABLE account_name_check (
    account_names_are_trimmed INTEGER CHECK (account_names_are_trimmed = 1)
);
INSERT INTO account_name_check
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM accounts WHERE name = '' OR name <> trim(name, ' ' || char(9, 10, 11, 12, 13))
    ) THEN 0 ELSE 1 END;
DROP TABLE account_name_check;

-- A v0.1 database may already hold duplicates. In each group of names that match ignoring case, the account with
-- the lowest id keeps its name and each later one, in id order, gets the smallest "Name (n)" (n of 2 or more) that
-- no account has. The first account's spelling is used for the base. Two renamed accounts can never collide with
-- each other: a name ends in its own " (n)", so the same new name could only come from the same group, and within
-- a group each account takes a different one of the unused numbers.
CREATE TEMP TABLE account_renames AS
WITH RECURSIVE
ranked AS (
    SELECT id, name, ROW_NUMBER() OVER (PARTITION BY name COLLATE NOCASE ORDER BY id) AS place
    FROM accounts
),
groups AS (
    SELECT first.name AS base
    FROM ranked first
    WHERE first.place = 1
      AND EXISTS (SELECT 1 FROM ranked later WHERE later.place = 2 AND later.name = first.name COLLATE NOCASE)
),
numbers (n) AS (
    SELECT 2
    UNION ALL
    SELECT n + 1 FROM numbers WHERE n < (SELECT 2 * COUNT(*) + 2 FROM accounts)   -- always enough unused numbers
),
unused AS (
    SELECT groups.base, numbers.n,
           ROW_NUMBER() OVER (PARTITION BY groups.base ORDER BY numbers.n) AS pick
    FROM groups CROSS JOIN numbers
    WHERE NOT EXISTS (
        SELECT 1 FROM accounts WHERE name = groups.base || ' (' || numbers.n || ')' COLLATE NOCASE
    )
)
SELECT ranked.id AS id, unused.base || ' (' || unused.n || ')' AS new_name
FROM ranked
JOIN groups ON groups.base = ranked.name COLLATE NOCASE
JOIN unused ON unused.base = groups.base AND unused.pick = ranked.place - 1
WHERE ranked.place > 1;

UPDATE accounts
SET name = (SELECT new_name FROM account_renames WHERE account_renames.id = accounts.id)
WHERE id IN (SELECT id FROM account_renames);

DROP TABLE account_renames;

CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE);

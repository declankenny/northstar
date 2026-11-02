-- Account soft delete. See docs/spec.md, "Rules" (Deleting), and docs/design/v0.2-db-schema.
-- A deleted account keeps its row and its balances, which leave every view with it. Restoring comes later (v0.5). Reads go
-- through the two views below, so a query cannot forget the filter; a test fails on a direct read of accounts or balances.
--
-- Anything that later rebuilds accounts or balances must first drop these views and create them again afterwards, because
-- SQLite cannot rename a table while a view refers to it.

ALTER TABLE accounts ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1));

-- A deleted account frees its name. A closed account still holds it.
DROP INDEX accounts_name_unique;
CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE) WHERE deleted = 0;

CREATE VIEW live_accounts AS
    SELECT * FROM accounts WHERE deleted = 0;

CREATE VIEW live_balances AS
    SELECT balances.* FROM balances JOIN accounts ON accounts.id = balances.account_id WHERE accounts.deleted = 0;

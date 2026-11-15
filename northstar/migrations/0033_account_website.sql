-- A website for an account (#266): the address of the bank's own site, so the account page can link to it.
--
-- Optional, and only ever a cleaned http or https address (accounts.clean_website): no user name or password, no query string, no
-- fragment. The rule is in code; the CHECK only keeps a stored value to the length the rule allows. No existing row changes.
--
-- A plain ADD COLUMN is enough: live_accounts and account_summaries read `accounts.*` and pick the new column up as they are.

ALTER TABLE accounts ADD COLUMN website TEXT CHECK (website IS NULL OR length(website) <= 2048);

INSERT INTO sys_audited_fields (tablename, fieldname, is_logged) VALUES ('accounts', 'website', 1);

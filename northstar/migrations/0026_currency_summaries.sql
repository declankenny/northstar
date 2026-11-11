-- The Currencies list (the lists framework, v0.5): each currency with how many accounts use it, so the list can sort and filter by it.
--
-- account_count is the number of live accounts in the currency, open or closed and not deleted (the rule the old Currencies page
-- had). The columns of the currency come first (`c.*`, so that the framework reads its key and the rest of the catalog), then the count.
-- The view says nothing about the system currency: a currency's stored flag is shown as it is.
--
-- It reads live_accounts, so a later rebuild of accounts or balances must drop it first, with the other views, and create it
-- again afterwards.

CREATE VIEW currency_summaries AS
SELECT c.*,
       (SELECT COUNT(*) FROM live_accounts a WHERE a.currency_id = c.id) AS account_count
FROM currencies c;

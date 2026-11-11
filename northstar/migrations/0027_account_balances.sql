-- The account page's balance history as a list of the framework (the lists framework, v0.5): each live balance with how much it changed
-- from the account's balance before it.
--
-- change_cents is this balance minus the one before it on the same account, in date order, and empty for the account's first balance.
-- The window runs over every live balance of the account, whatever list reads the view and however it is filtered or paged, so a page
-- of the history shows the true change from the balance before it, even when that balance is on the page before. The columns of the
-- balance come first (`b.*`, so that the framework reads its key and relations), then the change. It is in the account's own
-- currency, like the balance.
--
-- It reads live_balances, so a later rebuild of accounts or balances must drop it first, with the other views, and create it again
-- afterwards.

CREATE VIEW account_balances AS
SELECT b.*,
       b.amount_cents - LAG(b.amount_cents) OVER (PARTITION BY b.account_id ORDER BY b.as_of_date) AS change_cents
FROM live_balances b;

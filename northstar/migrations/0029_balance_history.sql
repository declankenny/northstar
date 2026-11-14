-- One balance's history as a list of the framework (the lists framework, v0.5): each recorded change to a live balance, read from the
-- change log, for the balance page. History and recovery, step 1 (#58, docs/design/history-and-recovery).
--
-- A row is a change the log recorded for a balance that is live (the balance exists and its account is not deleted): an INSERT, or an
-- UPDATE of a logged field. A DELETE entry is not a row, because a deleted balance has no page. Its columns:
--   id          the negative of the log entry's id, or the balance's own id for the baseline row (below), so it is unique. The framework
--               breaks a tie in the sort by the smallest id, and two changes in the same second have the same time, so this puts the
--               later entry first when newest is first, and the baseline row after the changes it came before
--   balance_id  the balance
--   changed_at  when the operation happened (UTC), and by_name who made it: the balance's creator for the baseline row
--   amount_cents  the amount the balance had after the change, in the account's own currency. An UPDATE of the note alone does not
--               carry the amount, so it is the amount of the latest earlier entry that did, else the amount before the first logged
--               change, else the amount now
--   scale, unit the account's currency places and code, so the list can write the amount without a relation to the account
--   is_current  1 for the latest row of the balance
--   how         what produced the change, in words: "Manual edit", "Update balances", "CSV import", "Import undo" or "Command line", then
--               " · " and the base name of the imported file for an import, then " · note changed" when the change edited the note. The page
--               writes what follows the first " · " in a quieter colour
--
-- A balance that existed before the log, or whose creation the log never saw, has no INSERT entry. It gets one baseline row, the
-- earliest known value: its amount before the first logged change (or its amount now when nothing was logged), dated and authored
-- as the balance was created. No history before the log is implied.
--
-- It reads live_balances and live_accounts, so a later rebuild of accounts or balances must drop it first, with the other views,
-- and create it again afterwards. The log keeps no foreign key to a record, so the view reads it by table name and record id.

CREATE VIEW balance_history AS
WITH entries AS (
    SELECT c.id AS id, c.record_id AS balance_id, c.change AS change, c.old_json AS old_json, c.new_json AS new_json,
           o.created_at AS changed_at, o.user_id AS user_id, o.kind AS kind, o.detail AS detail
    FROM sys_record_changes c JOIN sys_operations o ON o.id = c.operation_id
    WHERE c.tablename = 'balances' AND c.change IN ('INSERT', 'UPDATE')
),
-- The amount before the first logged change: the old amount of the first entry that changed it, else the amount now.
baseline(balance_id, amount_cents) AS (
    SELECT lb.id,
           COALESCE((SELECT json_extract(x.old_json, '$.amount_cents') FROM entries x
                      WHERE x.balance_id = lb.id AND json_type(x.old_json, '$.amount_cents') IS NOT NULL
                      ORDER BY x.id LIMIT 1), lb.amount_cents)
    FROM live_balances lb
)
SELECT -e.id AS id,
       e.balance_id AS balance_id,
       e.changed_at AS changed_at,
       u.display_name AS by_name,
       COALESCE((SELECT json_extract(x.new_json, '$.amount_cents') FROM entries x
                  WHERE x.balance_id = e.balance_id AND x.id <= e.id AND json_type(x.new_json, '$.amount_cents') IS NOT NULL
                  ORDER BY x.id DESC LIMIT 1),
                (SELECT bl.amount_cents FROM baseline bl WHERE bl.balance_id = e.balance_id)) AS amount_cents,
       cur.minor_units AS scale,
       cur.code AS unit,
       NOT EXISTS (SELECT 1 FROM entries x WHERE x.balance_id = e.balance_id AND x.id > e.id) AS is_current,
       CASE e.kind WHEN 'ui_edit' THEN 'Manual edit' WHEN 'bulk_update' THEN 'Update balances' WHEN 'import' THEN 'CSV import'
                   WHEN 'undo' THEN 'Import undo' WHEN 'cli' THEN 'Command line' ELSE e.kind END
       || CASE WHEN e.kind = 'import' AND json_extract(e.detail, '$.file') IS NOT NULL THEN ' · ' || json_extract(e.detail, '$.file') ELSE '' END
       || CASE WHEN e.change = 'UPDATE' AND json_type(e.new_json, '$.note') IS NOT NULL THEN ' · note changed' ELSE '' END AS how
FROM entries e
JOIN live_balances lb ON lb.id = e.balance_id
JOIN live_accounts a ON a.id = lb.account_id
JOIN currencies cur ON cur.id = a.currency_id
JOIN users u ON u.id = e.user_id

UNION ALL

SELECT lb.id, lb.id, lb.created_at, u.display_name,
       (SELECT bl.amount_cents FROM baseline bl WHERE bl.balance_id = lb.id),
       cur.minor_units, cur.code,
       NOT EXISTS (SELECT 1 FROM entries x WHERE x.balance_id = lb.id),
       'Entered'
FROM live_balances lb
JOIN live_accounts a ON a.id = lb.account_id
JOIN currencies cur ON cur.id = a.currency_id
JOIN users u ON u.id = lb.created_by
WHERE NOT EXISTS (SELECT 1 FROM sys_record_changes c WHERE c.tablename = 'balances' AND c.record_id = lb.id AND c.change = 'INSERT');

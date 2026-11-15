-- The history of a balance that was restored from the Deleted balances screen (history and recovery, step 5: #271).
--
-- A balance the log never saw created (one from before the log) has no INSERT entry, so its history gets one baseline row, "Entered", with
-- its earliest known amount, dated and authored as it was created (migration 0029). Restoring a deleted balance writes an INSERT, which
-- stopped that row from appearing, and the writer stamps the restored row as created by the person who restored it. The view is made again
-- with two changes and nothing else:
--   * an INSERT made by a `restore` operation is not a creation, so it does not stop the baseline row. A restored balance of the log's
--     own making, with an INSERT of its own, still has no baseline row, as before
--   * the baseline row is dated and authored as the balance was first created, which the first DELETE entry for it recorded, and not
--     as it was restored (a balance that was never deleted has no such entry, and uses its own columns as before)
-- The rest of the view is as it was, so a row has the same id, amount and order. It reads live_balances and live_accounts, so a later
-- rebuild of accounts or balances must drop it first, with the other views, and create it again afterwards.

DROP VIEW balance_history;

CREATE VIEW balance_history AS
WITH entries AS (
    SELECT c.id AS id, c.record_id AS balance_id, c.change AS change, c.old_json AS old_json, c.new_json AS new_json,
           o.created_at AS changed_at, o.user_id AS user_id, o.kind AS kind, o.detail AS detail
    FROM sys_record_changes c JOIN sys_operations o ON o.id = c.operation_id
    WHERE c.tablename = 'balances' AND c.change IN ('INSERT', 'UPDATE')
),
-- Where a balance's creation was first recorded: the first DELETE entry holds the creator and time it had then, which a restore does not carry over.
origin(balance_id, created_at, created_by) AS (
    SELECT c.record_id, json_extract(c.old_json, '$.created_at'), json_extract(c.old_json, '$.created_by')
    FROM sys_record_changes c
    WHERE c.tablename = 'balances' AND c.change = 'DELETE'
      AND c.id = (SELECT MIN(d.id) FROM sys_record_changes d WHERE d.tablename = 'balances' AND d.record_id = c.record_id AND d.change = 'DELETE')
),
-- The amount before the first logged change: the old amount of the first entry that changed it, else the amount now.
baseline(balance_id, amount_cents) AS (
    SELECT lb.id,
           COALESCE((SELECT json_extract(x.old_json, '$.amount_cents') FROM entries x
                      WHERE x.balance_id = lb.id AND json_type(x.old_json, '$.amount_cents') IS NOT NULL
                      ORDER BY x.id LIMIT 1), lb.amount_cents)
    FROM live_balances lb
),
history AS (
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
                       WHEN 'undo' THEN 'Import undo' WHEN 'cli' THEN 'Command line' WHEN 'restore' THEN 'Restored' ELSE e.kind END
           || CASE WHEN e.kind = 'import' AND json_extract(e.detail, '$.file') IS NOT NULL THEN ' · ' || json_extract(e.detail, '$.file') ELSE '' END
           || CASE WHEN e.kind = 'restore' AND json_extract(e.detail, '$.from') IS NOT NULL THEN ' · value of ' || json_extract(e.detail, '$.from') ELSE '' END
           || CASE WHEN e.change = 'UPDATE' AND json_type(e.new_json, '$.note') IS NOT NULL THEN ' · note changed' ELSE '' END AS how,
           e.change = 'INSERT' OR json_type(e.new_json, '$.amount_cents') IS NOT NULL AS sets_amount
    FROM entries e
    JOIN live_balances lb ON lb.id = e.balance_id
    JOIN live_accounts a ON a.id = lb.account_id
    JOIN currencies cur ON cur.id = a.currency_id
    JOIN users u ON u.id = e.user_id

    UNION ALL

    SELECT lb.id, lb.id, COALESCE(og.created_at, lb.created_at), u.display_name,
           (SELECT bl.amount_cents FROM baseline bl WHERE bl.balance_id = lb.id),
           cur.minor_units, cur.code,
           NOT EXISTS (SELECT 1 FROM entries x WHERE x.balance_id = lb.id),
           'Entered', 1
    FROM live_balances lb
    LEFT JOIN origin og ON og.balance_id = lb.id
    JOIN live_accounts a ON a.id = lb.account_id
    JOIN currencies cur ON cur.id = a.currency_id
    JOIN users u ON u.id = COALESCE(og.created_by, lb.created_by)
    WHERE NOT EXISTS (SELECT 1 FROM sys_record_changes c JOIN sys_operations o ON o.id = c.operation_id
                      WHERE c.tablename = 'balances' AND c.record_id = lb.id AND c.change = 'INSERT' AND o.kind != 'restore')
)
SELECT h.id AS id, h.balance_id AS balance_id, h.changed_at AS changed_at, h.by_name AS by_name, h.amount_cents AS amount_cents,
       h.scale AS scale, h.unit AS unit, h.is_current AS is_current, h.how AS how,
       h.sets_amount AND h.amount_cents <> lb.amount_cents AS restorable
FROM history h
JOIN live_balances lb ON lb.id = h.balance_id;

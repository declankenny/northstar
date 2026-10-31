import { useEffect, useState } from "react";
import {
  type AccountPage as Account, addBalance, type BalanceRow, changeClass, closeAccount, deleteAccount,
  deleteBalance, editAccount, editBalance, fetchAccount, fetchNetWorth, type NetWorthSeries, reopenAccount,
} from "./api";
import { BalanceDialog, ChangeClassDialog, EditAccountDialog } from "./AccountDialogs";
import { formatDate } from "./dates";
import { ConfirmDialog } from "./Dialogs";
import { formatCents, percentChange } from "./money";
import { NetWorthChart } from "./NetWorthChart";
import { PERIOD, RANGES, type Range, rangeStart } from "./ranges";
import { WHEN } from "./Tile";

type Dialog =
  | { kind: "balance"; editing: BalanceRow | null }
  | { kind: "edit" }
  | { kind: "class" }
  | { kind: "close" }
  | { kind: "delete-account" }
  | { kind: "delete-balance"; index: number };

/** An account's balance on a date: the server puts it in assets or liabilities by class, and one of them is zero. */
const balanceOf = (point: { assets: number; liabilities: number }) => point.assets + point.liabilities;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function ago(days: number | null): string {
  if (days === null) return "";
  return days === 0 ? "today" : `${plural(days, "day")} ago`;
}

/** What deleting a balance does to the account's history, from where that entry sits in the list (newest first). */
function deleteConsequence(balances: BalanceRow[], index: number): string {
  const entry = balances[index];
  const head = `The ${formatCents(entry.amount_cents)} entry for ${formatDate(entry.as_of_date)} is removed. `;
  if (balances.length === 1) return head + "It is the only balance, so this account will have no history.";
  if (index === balances.length - 1) {
    return head + `It is the first balance, so the history will start at the next entry, on ${formatDate(balances[index - 1].as_of_date)}.`;
  }
  const before = balances[index + 1];
  return head + `Until the next entry, the balance will go back to ${formatCents(before.amount_cents)} (entered ${formatDate(before.as_of_date)}).`;
}

export function AccountPage({ id }: { id: number }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("1Y");
  const [view, setView] = useState<{ range: Range; data: NetWorthSeries } | null>(null);
  const [version, setVersion] = useState(0); // bumped on every change, so the chart is asked again
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    setAccount(null);
    setView(null);
    setError(null);
    fetchAccount(id).then(setAccount, (e: Error) => setError(e.message));
  }, [id]);

  // The chart is the same series endpoint as the Dashboard, limited to this account.
  const today = account?.today;
  const hasBalances = (account?.balance_count ?? 0) > 0;
  useEffect(() => {
    if (!today || !hasBalances) return;
    let current = true;
    fetchNetWorth({ accountId: id, start: rangeStart(range, today), period: PERIOD[range] }).then(
      (data) => { if (current) setView({ range, data }); },
      (e: Error) => { if (current) setError(e.message); },
    );
    return () => { current = false; };
  }, [id, today, hasBalances, range, version]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menu]);

  if (error) return <p className="empty">Could not load this account. {error} <a href="#/accounts">Back to Accounts</a></p>;
  if (!account) return <p className="empty">Loading…</p>;

  /** Every change answers with the account as it now is. */
  const apply = (page: Account) => {
    setAccount(page);
    setVersion((v) => v + 1);
    setDialog(null);
  };
  const liability = account.class_name === "Liability";
  const open = account.is_open;
  const series = view && hasBalances ? view.data.series : [];
  const first = series.length ? balanceOf(series[0]) : 0;
  const last = series.length ? balanceOf(series[series.length - 1]) : 0;
  const diff = last - first;
  const pct = percentChange(diff, first);
  const good = diff === 0 ? null : diff > 0 === !liability;
  const sign = diff >= 0 ? "+" : "-";
  const inRange = view ? account.balances.filter((b) => b.as_of_date >= view.data.start).length : 0;

  return (
    <div className="acct">
      <div className="crumb"><a href="#/accounts">Accounts</a> / {account.name}</div>
      <div className="top">
        <div>
          <div className="titlerow">
            <h1>{account.name}</h1>
            <span className="badge plain">{account.type_name} · {account.class_name}</span>
            {!open && <span className="badge plain">Closed</span>}
            {account.stale && <span className="badge stale">Stale</span>}
          </div>
          <div className="sub">
            {!open
              ? "This account is closed. Reopen it to add or change its balances."
              : account.earliest_date ? `First balance on ${formatDate(account.earliest_date)}` : "No balances yet"}
          </div>
        </div>
        <div className="actions-bar">
          <button className="btn" disabled={!open} onClick={() => setDialog({ kind: "balance", editing: null })}>Add balance</button>
          <button className="btn ghost" aria-label="More actions" aria-haspopup="menu" aria-expanded={menu}
            onClick={(e) => { e.stopPropagation(); setMenu(!menu); }}>⋯</button>
          {menu && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={() => setDialog({ kind: "edit" })}>Edit account</button>
              <button role="menuitem" onClick={() => setDialog({ kind: "class" })}>Change class…</button>
              {open
                ? <button role="menuitem" onClick={() => setDialog({ kind: "close" })}>Close account…</button>
                : <button role="menuitem" onClick={() => reopenAccount(id).then(apply, (e: Error) => setError(e.message))}>Reopen account</button>}
              <hr />
              <button role="menuitem" className="bad" onClick={() => setDialog({ kind: "delete-account" })}>Delete account…</button>
            </div>
          )}
        </div>
      </div>

      <div className="tiles">
        <div className="tile main">
          <div className="label">Latest balance</div>
          <div className="val num">{account.last_cents === null ? "—" : formatCents(account.last_cents)}</div>
          <div className="delta num">
            <span className="m">
              {account.last_date ? `as of ${formatDate(account.last_date)} · ${ago(account.days_since)}` : "No balances yet"}
            </span>
            {account.stale && account.last_date && <span className="w"> · older than {account.stale_after_days} days</span>}
          </div>
        </div>
        <div className="tile">
          <div className="label">Change</div>
          <div className="val num">{view ? `${sign}${formatCents(Math.abs(diff))}` : "—"}</div>
          <div className="delta num">
            {view && (
              <>
                {pct !== null && <span className={good === null ? "m" : good ? "p" : "n"}>{sign}{Math.abs(pct).toFixed(1)}%</span>}{" "}
                <span className="m">{WHEN[view.range]}</span>
              </>
            )}
          </div>
        </div>
        <div className="tile">
          <div className="label">Balances recorded</div>
          <div className="val num">{view ? inRange : "—"}</div>
          <div className="delta num m">
            {view && `since ${formatDate(view.data.start)} · ${account.balance_count} in all`}
          </div>
        </div>
      </div>

      <div className="acct-body">
        <div className="acct-panel">
          <div className="panelhead">
            <span className="label">Balance history</span>
            {hasBalances && (
              <div className="ranges" role="group" aria-label="Date range">
                {RANGES.map((r) => (
                  <button key={r} className={r === range ? "on" : ""} aria-pressed={r === range} onClick={() => setRange(r)}>{r}</button>
                ))}
              </div>
            )}
          </div>
          {view && hasBalances ? (
            <NetWorthChart
              data={view.data}
              value={balanceOf}
              label={`${account.name} balance over time`}
              tip={(point) => (
                <>
                  <span>{formatDate(point.date)}</span>
                  <b>{formatCents(balanceOf(point))}</b>
                </>
              )}
            />
          ) : (
            <p className="empty pad">{hasBalances ? "Loading…" : "Add the first balance to start this account's history."}</p>
          )}
        </div>

        <div className="acct-panel">
          <div className="panelhead">
            <span className="label">Entries</span>
            {hasBalances && <span className="label num">{account.balance_count} total</span>}
          </div>
          <div className="hist">
            {hasBalances && (
              <table className="num">
                <thead>
                  <tr><th>Date</th><th className="r">Balance</th><th className="r">Change</th><th /></tr>
                </thead>
                <tbody>
                  {account.balances.map((b, i) => {
                    const older = account.balances[i + 1];
                    const step = older ? b.amount_cents - older.amount_cents : null;
                    const stepGood = step === null || step === 0 ? "m" : step > 0 === !liability ? "p" : "n";
                    return (
                      <tr key={b.id}>
                        <td>
                          {formatDate(b.as_of_date)}
                          {b.note && <div className="rownote" title={b.note}>{b.note}</div>}
                        </td>
                        <td className="r">{formatCents(b.amount_cents)}</td>
                        <td className={`r ${stepGood}`}>
                          {step === null ? "—" : `${step >= 0 ? "+" : "-"}${formatCents(Math.abs(step))}`}
                        </td>
                        <td className="row-actions">
                          {open && (
                            <span>
                              <button onClick={() => setDialog({ kind: "balance", editing: b })}>Edit</button>
                              <button className="bad" onClick={() => setDialog({ kind: "delete-balance", index: i })}>Delete</button>
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {dialog?.kind === "balance" && (
        <BalanceDialog account={account} editing={dialog.editing} onClose={() => setDialog(null)}
          onSave={async (entry) => apply(dialog.editing ? await editBalance(dialog.editing.id, entry) : await addBalance(id, entry))} />
      )}
      {dialog?.kind === "edit" && (
        <EditAccountDialog account={account} onClose={() => setDialog(null)}
          onSave={async (change) => apply(await editAccount(id, change))} />
      )}
      {dialog?.kind === "class" && (
        <ChangeClassDialog account={account} onClose={() => setDialog(null)}
          onSave={async (typeId) => apply(await changeClass(id, typeId))} />
      )}
      {dialog?.kind === "close" && (
        <ConfirmDialog title={`Close ${account.name}?`} confirmLabel="Close account" onClose={() => setDialog(null)}
          text="A closed account leaves Update balances and the open accounts list, and its balances can't be changed. Its history stays in net worth. You can reopen it later. Its latest balance must be zero."
          onConfirm={async () => apply(await closeAccount(id))} />
      )}
      {dialog?.kind === "delete-balance" && (
        <ConfirmDialog title="Delete this balance?" confirmLabel="Delete" danger onClose={() => setDialog(null)}
          text={deleteConsequence(account.balances, dialog.index)}
          onConfirm={async () => apply(await deleteBalance(account.balances[dialog.index].id))} />
      )}
      {dialog?.kind === "delete-account" && (
        <ConfirmDialog title={`Delete ${account.name}?`} confirmLabel="Delete account" danger onClose={() => setDialog(null)}
          text={`This permanently deletes the account${account.balance_count ? ` and its ${plural(account.balance_count, "balance")}` : ""}. Net worth history changes to match. This can't be undone. To hide an account but keep its history, close it instead.`}
          onConfirm={async () => { await deleteAccount(id); window.location.hash = "#/accounts"; }} />
      )}
    </div>
  );
}

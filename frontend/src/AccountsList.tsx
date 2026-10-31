import { useEffect, useState } from "react";
import { type AccountList, addAccount, fetchAccounts, type ListedAccount } from "./api";
import { AddAccountDialog } from "./AccountDialogs";
import { formatDate } from "./dates";
import { formatCents } from "./money";

function ago(days: number | null): string {
  if (days === null) return "";
  return days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`;
}

function Row({ account, showStale }: { account: ListedAccount; showStale: boolean }) {
  const stale = showStale && account.stale;
  const open = () => { window.location.hash = `#/accounts/${account.id}`; };
  return (
    <tr className="row" onClick={open}>
      <td>
        <a className="name" href={`#/accounts/${account.id}`} onClick={(e) => e.stopPropagation()}>{account.name}</a>
        {stale && <span className="badge stale">Stale</span>}
      </td>
      <td className="m">{account.type_name}</td>
      <td className="r">{account.last_cents === null ? <span className="m">—</span> : formatCents(account.last_cents)}</td>
      <td>
        {account.last_date === null ? (
          <span className={stale ? "w" : "m"}>No balances yet</span>
        ) : (
          <>{formatDate(account.last_date)} <span className={stale ? "w" : "m"}>· {ago(account.days_since)}</span></>
        )}
      </td>
      <td className="r">{account.balance_count}</td>
      <td className="note" title={account.notes ?? undefined}>{account.notes}</td>
    </tr>
  );
}

export function AccountsList({ isAdmin }: { isAdmin: boolean }) {
  const [closed, setClosed] = useState(false);
  const [list, setList] = useState<AccountList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [adding, setAdding] = useState<"asset" | "liability" | null>(null);

  useEffect(() => {
    let current = true; // ignore an answer that arrives after the other list was chosen
    fetchAccounts(closed).then(
      (data) => { if (current) setList(data); },
      (e: Error) => { if (current) setError(e.message); },
    );
    return () => { current = false; };
  }, [closed]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menu]);

  if (error) return <p className="empty">Could not load accounts. {error}</p>;
  if (!list) return <p className="empty">Loading…</p>;

  const groups = [
    { name: "Assets", cls: "Asset", total: list.totals?.assets },
    { name: "Liabilities", cls: "Liability", total: list.totals?.liabilities },
  ].map((g) => ({ ...g, rows: list.accounts.filter((a) => a.class_name === g.cls) })).filter((g) => g.rows.length > 0);

  return (
    <div className="acct">
      <div className="top">
        <div>
          <div className="eyebrow">{formatDate(list.today).toUpperCase()}</div>
          <h1>Accounts</h1>
        </div>
        <div className="actions-bar">
          <button className="btn" aria-haspopup="menu" aria-expanded={menu}
            onClick={(e) => { e.stopPropagation(); setMenu(!menu); }}>Add account ▾</button>
          {menu && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={() => setAdding("asset")}>Asset account…</button>
              <button role="menuitem" onClick={() => setAdding("liability")}>Liability account…</button>
            </div>
          )}
        </div>
      </div>

      <div className="listbar">
        <div className="ranges" role="group" aria-label="Show">
          <button className={!closed ? "on" : ""} aria-pressed={!closed} onClick={() => setClosed(false)}>Open</button>
          <button className={closed ? "on" : ""} aria-pressed={closed} onClick={() => setClosed(true)}>Closed</button>
        </div>
      </div>

      <div className="acct-panel listpanel">
        <div className="hist">
          {groups.length === 0 ? (
            <p className="empty pad">{closed ? "No closed accounts." : "No open accounts yet. Use Add account to create one."}</p>
          ) : (
            <table className="num list">
              <colgroup>
                <col style={{ width: "22%" }} /><col style={{ width: "13%" }} /><col style={{ width: "15%" }} />
                <col style={{ width: "20%" }} /><col style={{ width: "9%" }} /><col />
              </colgroup>
              <thead>
                <tr><th>Account</th><th>Type</th><th className="r">Latest balance</th><th>As of</th><th className="r">Balances</th><th className="note">Notes</th></tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <GroupRows key={g.cls} name={g.name} total={g.total} rows={g.rows} showStale={!closed} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {adding && (
        <AddAccountDialog list={list} isAdmin={isAdmin} accountClass={adding} onClose={() => setAdding(null)}
          onSave={async (account) => {
            const fresh = await addAccount(account); // answers with the open list, which now has the new account
            setClosed(false);
            setList(fresh);
            setAdding(null);
          }} />
      )}
    </div>
  );
}

function GroupRows(props: { name: string; total: number | undefined; rows: ListedAccount[]; showStale: boolean }) {
  return (
    <>
      <tr className="sect">
        <td colSpan={2}>{props.name}</td>
        <td className="r">{props.total === undefined ? "" : formatCents(props.total)}</td>
        <td colSpan={3} />
      </tr>
      {props.rows.map((a) => <Row key={a.id} account={a} showStale={props.showStale} />)}
    </>
  );
}

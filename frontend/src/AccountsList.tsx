import { useEffect, useState } from "react";
import {
  type AccountList, type AccountPage, addAccount, addBalance, editAccount, fetchAccount, fetchAccounts, type ListedAccount,
} from "./api";
import { AddAccountDialog, BalanceDialog, EditAccountDialog } from "./AccountDialogs";
import { formatDate } from "./dates";
import { formatCents } from "./money";
import { RowMenu } from "./RowMenu";

function ago(days: number | null): string {
  if (days === null) return "";
  return days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`;
}

type RowActions = { onEdit: (a: ListedAccount) => void; onAddBalance: (a: ListedAccount) => void };

function Row({ account, showStale, actions }: { account: ListedAccount; showStale: boolean; actions: RowActions }) {
  const stale = showStale && account.stale;
  const items = [
    { label: "Open", onClick: () => { window.location.hash = `#/accounts/${account.id}`; } },
    { label: "Edit", onClick: () => actions.onEdit(account) },
    // A closed account takes no new balances, so its menu has no Add balance.
    ...(showStale ? [{ label: "Add balance", onClick: () => actions.onAddBalance(account) }] : []),
  ];
  return (
    <tr className="row">
      <td>
        <a className="name" href={`#/accounts/${account.id}`}>{account.name}</a>
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
      <td className="k"><RowMenu label={`Actions for ${account.name}`} items={items} /></td>
    </tr>
  );
}

export function AccountsList({ isAdmin }: { isAdmin: boolean }) {
  const [closed, setClosed] = useState(false);
  const [list, setList] = useState<AccountList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [adding, setAdding] = useState<"asset" | "liability" | null>(null);
  const [dialog, setDialog] = useState<{ kind: "edit" | "balance"; account: AccountPage } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

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

  // The dialogs take the whole account, so fetch it first; the list only carries what its table shows.
  const openDialog = (kind: "edit" | "balance") => (listed: ListedAccount) => {
    setFailure(null);
    fetchAccount(listed.id).then((account) => setDialog({ kind, account }), (e: Error) => setFailure(e.message));
  };
  const actions: RowActions = { onEdit: openDialog("edit"), onAddBalance: openDialog("balance") };
  /** A change is saved on the account, then the list is read again so the row and its group total are right. */
  const saved = async () => {
    setList(await fetchAccounts(closed));
    setDialog(null);
  };

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

      {failure && <p className="notice bad" role="alert">{failure}</p>}

      <div className="stack">
        {groups.length === 0 ? (
          <div className="gcard"><p className="empty pad">{closed ? "No closed accounts." : "No open accounts yet. Use Add account to create one."}</p></div>
        ) : (
          groups.map((g) => (
            <div key={g.cls} className={`gcard ${g.cls.toLowerCase()}`}>
              <div className="gh">
                <span className="gt">{g.name}</span>
                {g.total !== undefined && <span className="tot num">{formatCents(g.total)}</span>}
              </div>
              <table className="num list">
                <colgroup>
                  <col style={{ width: "21%" }} /><col style={{ width: "12%" }} /><col style={{ width: "15%" }} />
                  <col style={{ width: "20%" }} /><col style={{ width: "8%" }} /><col /><col style={{ width: "64px" }} />
                </colgroup>
                <thead>
                  <tr><th>Account</th><th>Type</th><th className="r">Latest balance</th><th>As of</th><th className="r">Balances</th><th className="note">Notes</th><th /></tr>
                </thead>
                <tbody>
                  {g.rows.map((a) => <Row key={a.id} account={a} showStale={!closed} actions={actions} />)}
                </tbody>
              </table>
            </div>
          ))
        )}
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

      {dialog?.kind === "edit" && (
        <EditAccountDialog account={dialog.account} onClose={() => setDialog(null)}
          onSave={async (change) => { await editAccount(dialog.account.id, change); await saved(); }} />
      )}
      {dialog?.kind === "balance" && (
        <BalanceDialog account={dialog.account} editing={null} onClose={() => setDialog(null)}
          onSave={async (entry) => { await addBalance(dialog.account.id, entry); await saved(); }} />
      )}
    </div>
  );
}

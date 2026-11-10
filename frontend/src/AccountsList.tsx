import { useEffect, useState } from "react";
import { addAccount, fetchAccountOptions } from "./api";
import { AddAccountDialog } from "./AccountDialogs";
import { ListView } from "./ListView";
import { useRequest } from "./useRequest";

/** Every account, as a list of the framework: the columns, the sort and the shared "Open accounts" filter are data on the server, so
 *  this page is the heading, the Add account button and the table. An account's page has every action on it, so a row has no menu. */
export function AccountsList({ isAdmin }: { isAdmin: boolean }) {
  const { data: options, error } = useRequest((signal) => fetchAccountOptions(signal), []);
  const [menu, setMenu] = useState(false);
  const [adding, setAdding] = useState<"asset" | "liability" | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);      // raised when an account is added, so the list reads its rows again in place

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menu]);

  return (
    <div className="acct">
      <div className="top">
        <div><h1>Accounts</h1></div>
        <div className="actions-bar">
          <button className="btn" aria-haspopup="menu" aria-expanded={menu} disabled={!options}
            onClick={(e) => { e.stopPropagation(); setMenu(!menu); }}>Add account ▾</button>
          {menu && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={() => setAdding("asset")}>Asset account…</button>
              <button role="menuitem" onClick={() => setAdding("liability")}>Liability account…</button>
            </div>
          )}
        </div>
      </div>

      {error && <p className="notice bad" role="alert">Could not load what Add account offers. {error}</p>}
      {options?.currency === null && (
        <p className="notice warn" role="status">The system currency is not set yet. Set it before adding the first account.</p>
      )}

      <ListView listKey="accounts" refreshKey={refreshKey}
        config={{ title: "Accounts", isAdmin, emptyText: "There are no accounts yet. Use Add account to create one." }} />

      {adding && options && (
        <AddAccountDialog options={options} isAdmin={isAdmin} accountClass={adding} onClose={() => setAdding(null)}
          onSave={async (account) => {
            await addAccount(account);
            setRefreshKey((n) => n + 1);
            setAdding(null);
          }} />
      )}
    </div>
  );
}

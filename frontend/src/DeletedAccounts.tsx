import { useState } from "react";
import { type DeletedAccount, fetchDeletedAccounts, restoreAccount } from "./api";
import { formatDate } from "./dates";
import { Modal, useAction } from "./Dialogs";
import { setFlash } from "./flash";
import { plural } from "./importLogic";
import { navigate } from "./router";
import { accountPath } from "./routes";
import { useRequest } from "./useRequest";

/** Asks the admin to confirm, and for a new name when the old one is in use. A refusal stays in the dialog, and the list is read again so that
 *  a name taken since the page was drawn asks for a new one. */
function RestoreDialog({ entry, onRefused, onClose }: { entry: DeletedAccount; onRefused: () => void; onClose: () => void }) {
  const { busy, error, run } = useAction();
  const [name, setName] = useState(entry.name);
  const asking = entry.name_taken;
  const go = () => run(async () => {
    try {
      const restored = await restoreAccount(entry.id, asking ? name : undefined);
      setFlash(`${restored.name} was restored${restored.balance_count > 0 ? ` with ${plural(restored.balance_count, "balance")}` : ""}.`);
      navigate(accountPath(restored.id));
    } catch (e) {
      onRefused();
      throw e;
    }
  });
  return (
    <Modal title="Restore this account?" onClose={onClose}>
      <p className="sub">
        {entry.name} ({entry.type_name}) will be available again{entry.balance_count > 0 ? ` with the ${plural(entry.balance_count, "balance")} its deletion hid` : ""}.
        Balances deleted on their own before the account was deleted stay deleted. It stays {entry.is_open ? "open" : "closed"}.
      </p>
      {asking && (
        <>
          <p className="notice bad" role="status">Another account is now called {entry.name}. Choose a new name to restore this one. The other account is not changed.</p>
          <label>New name<input value={name} maxLength={200} onChange={(event) => setName(event.target.value)} autoFocus /></label>
        </>
      )}
      {error && <p className="notice bad" role="alert">{error}</p>}
      <div className="foot">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={busy || (asking && name.trim() === "")} autoFocus={!asking} onClick={go}>Restore account</button>
      </div>
    </Modal>
  );
}

/** The admin page listing deleted accounts, newest deletion first, with Restore. Every deleted account is listed: nothing here is cut off. */
export function DeletedAccounts() {
  const { data, error, reload } = useRequest(fetchDeletedAccounts, []);
  const [restoring, setRestoring] = useState<DeletedAccount | null>(null);
  // The dialog shows the entry as it is now, so a name taken since the page was drawn changes what it asks.
  const current = restoring && data ? data.accounts.find((entry) => entry.id === restoring.id) ?? restoring : restoring;

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Deleted accounts</h1>
          <p className="sub">Deleted accounts, newest first. Restore brings back the account and the balances its deletion hid.</p>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {data && !data.cleanup_on && (
        <p className="notice warn" role="status">The cleanup of deleted data is switched off, so deleted accounts are kept until it is switched on again.</p>
      )}
      {data && data.accounts.length === 0 && (
        <p className="empty">No deleted accounts. An account that is deleted is listed here until it is permanently deleted.</p>
      )}
      {data && data.accounts.length > 0 && (
        <div className="panel tablepanel">
          <table>
            <thead>
              <tr><th>Account</th><th>Type</th><th>Deleted</th><th>Permanently deleted on</th><th></th></tr>
            </thead>
            <tbody>
              {data.accounts.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.name}{!entry.is_open && <> <span className="badge">Closed</span></>}</td>
                  <td>{entry.type_name}</td>
                  <td className="num">{formatDate(entry.deleted_on)}</td>
                  <td className="num">{entry.purge_on === null ? "Not scheduled" : formatDate(entry.purge_on)}</td>
                  <td><button className="btn ghost small" onClick={() => setRestoring(entry)}>Restore account&hellip;</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {current && <RestoreDialog key={current.id} entry={current} onRefused={reload} onClose={() => setRestoring(null)} />}
    </div>
  );
}

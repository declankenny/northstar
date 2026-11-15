import { useState } from "react";
import { type DeletedBalance, fetchDeletedBalances, RequestError, restoreDeletedBalance } from "./api";
import { formatDate } from "./dates";
import { Modal, useAction } from "./Dialogs";
import { setFlash } from "./flash";
import { formatCents } from "./money";
import { Link, navigate } from "./router";
import { balancePath } from "./routes";
import { useRequest } from "./useRequest";

type Refusal = { message: string; existing: RequestError["existing"] };

/** Asks the admin to confirm. A refusal (a balance has the date now, the account is closed or deleted, or it is not deleted any more) is shown in
 *  the dialog with nothing written, and the list is read again so that it shows things as they are. */
function RestoreDialog({ entry, onRefused, onClose }: { entry: DeletedBalance; onRefused: () => void; onClose: () => void }) {
  const { busy, error, run } = useAction();
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const go = () => run(async () => {
    try {
      const restored = await restoreDeletedBalance(entry.id, entry.entry_id);
      setFlash(`The balance for ${formatDate(restored.as_of_date)} was restored.`);
      navigate(balancePath(restored.id));
    } catch (e) {
      if (e instanceof RequestError && [404, 409, 422].includes(e.status)) {
        setRefusal({ message: e.message, existing: e.existing });
        onRefused();
        return;
      }
      throw e;
    }
  });
  return (
    <Modal title="Restore this balance?" onClose={onClose}>
      <ul className="facts">
        <li>{entry.account_name}, {formatDate(entry.as_of_date)}</li>
        <li>Amount <b>{formatCents(entry.amount_cents, entry.currency)}</b>{entry.note ? <>, note &ldquo;{entry.note}&rdquo;</> : null}</li>
      </ul>
      {refusal === null && <p className="sub">The balance comes back as it was, and its history shows who restored it and when.</p>}
      {refusal && (
        <p className="notice bad" role="alert">
          <b>Nothing was restored.</b> {refusal.message}
          {refusal.existing && <> Its balance is {formatCents(refusal.existing.amount_cents, entry.currency)}. <Link to={balancePath(refusal.existing.balance_id)}>See that balance</Link>.</>}
        </p>
      )}
      {error && <p className="notice bad" role="alert">{error}</p>}
      <div className="foot">
        {refusal ? <button className="btn" autoFocus onClick={onClose}>Close</button> : (
          <>
            <button className="btn ghost" onClick={onClose}>Cancel</button>
            <button className="btn" disabled={busy} autoFocus onClick={go}>Restore balance</button>
          </>
        )}
      </div>
    </Modal>
  );
}

/** The admin page listing balances deleted on their own, newest deletion first, with an account filter and Restore. Every one is listed. */
export function DeletedBalances() {
  const { data, error, reload } = useRequest(fetchDeletedBalances, []);
  const [account, setAccount] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<DeletedBalance | null>(null);
  const accounts = data ? [...new Map(data.balances.map((entry) => [entry.account_id, entry.account_name])).entries()].sort((a, b) => a[1].localeCompare(b[1])) : [];
  // A filter on an account that has nothing deleted any more (its last one was just restored) shows everything again.
  const filter = account !== null && accounts.some(([id]) => id === account) ? account : null;
  const shown = data ? data.balances.filter((entry) => filter === null || entry.account_id === filter) : [];

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Deleted balances</h1>
          <p className="sub">
            Balances deleted on their own, newest first. Restore puts one back with its amount and note. Balances of deleted accounts return with Restore account.
          </p>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {data && !data.cleanup_on && (
        <p className="notice warn" role="status">The cleanup of deleted data is switched off, so deleted balances are kept until it is switched on again.</p>
      )}
      {data && data.balances.length === 0 && (
        <p className="empty">No deleted balances. A balance that is deleted is listed here until it is permanently deleted.</p>
      )}
      {data && data.balances.length > 0 && (
        <>
          <div className="filter">
            <label>Account{" "}
              <select value={filter ?? ""} onChange={(event) => setAccount(event.target.value === "" ? null : Number(event.target.value))}>
                <option value="">All accounts</option>
                {accounts.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
            </label>
          </div>
          <div className="panel tablepanel">
            <table>
              <thead>
                <tr>
                  <th>Account</th><th>Balance date</th><th className="r">Amount</th><th>Deleted by</th><th>Deleted</th><th>Permanently deleted on</th><th></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.account_name}{!entry.account_open && <> <span className="badge">Closed</span></>}</td>
                    <td className="num">{formatDate(entry.as_of_date)}</td>
                    <td className="num r">{formatCents(entry.amount_cents, entry.currency)}</td>
                    <td>{entry.deleted_by}</td>
                    <td className="num">{formatDate(entry.deleted_on)}</td>
                    <td className="num">{entry.purge_on === null ? "Not scheduled" : formatDate(entry.purge_on)}</td>
                    <td><button className="btn ghost small" onClick={() => setRestoring(entry)}>Restore balance&hellip;</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {restoring && <RestoreDialog key={restoring.id} entry={restoring} onRefused={reload} onClose={() => setRestoring(null)} />}
    </div>
  );
}

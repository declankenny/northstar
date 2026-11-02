import { useState } from "react";
import { fetchImports, fetchUndoPlan, type ImportEntry, undoImport, type UndoDone, type UndoPlan, type UndoRefusal } from "./api";
import { Modal, useAction } from "./Dialogs";
import { plural } from "./importLogic";
import { Link } from "./router";
import { accountPath } from "./routes";
import { useRequest } from "./useRequest";

function AccountCell({ entry }: { entry: ImportEntry }) {
  if (entry.account_id === null) return <span className="reverted">Unknown account</span>;
  if (entry.account_deleted) return <span className="reverted">(deleted account)</span>;
  return (
    <>
      <Link to={accountPath(entry.account_id)}>{entry.account_name}</Link>
      {!entry.account_open && <span className="badge">Closed</span>}
    </>
  );
}

/** Which import, in words: "savings.csv, imported into Demo Savings on 2026-11-02 by Demo Admin." */
function describe(entry: ImportEntry): string {
  const where = entry.account_name === null ? "" : ` into ${entry.account_name}`;
  return `${entry.file ?? "An unnamed file"}, imported${where} on ${entry.date} by ${entry.by}.`;
}

function Refused({ entry, refusal, onClose }: { entry: ImportEntry; refusal: UndoRefusal; onClose: () => void }) {
  return (
    <Modal title={"This import can’t be undone yet"} subtitle={describe(entry)} onClose={onClose}>
      {refusal.reason === "changed" ? (
        <>
          <p className="sub">Some of its balances have changed since, and Undo does not overwrite later changes.</p>
          <div className="why">
            <table>
              <tbody>
                {refusal.blocked.map((item) => (
                  <tr key={item.date}><td className="num">{item.date}</td><td>{item.why}</td></tr>
                ))}
              </tbody>
            </table>
            {refusal.more > 0 && <p className="sub">and {refusal.more.toLocaleString("en-US")} more.</p>}
          </div>
          <p className="sub">Nothing was changed. Fix these balances by hand, then try Undo again.</p>
        </>
      ) : (
        <>
          <p className="why-text">{refusal.message}</p>
          <p className="sub">Nothing was changed.</p>
        </>
      )}
      <div className="foot"><button className="btn" autoFocus onClick={onClose}>Close</button></div>
    </Modal>
  );
}

function Confirm({ entry, plan, onDone, onRefused, onClose }: {
  entry: ImportEntry; plan: UndoPlan; onDone: (done: UndoDone) => void; onRefused: (refusal: UndoRefusal) => void; onClose: () => void;
}) {
  const { busy, error, run } = useAction();
  const go = () => run(async () => {
    const answer = await undoImport(entry.id);
    if (answer.refused) onRefused(answer);
    else onDone(answer);
  });
  return (
    <Modal title="Undo this import?" subtitle={describe(entry)} onClose={onClose}>
      <ul className="facts">
        {plan.delete > 0 && <li>{plural(plan.delete, "balance")} the import added will be <b>deleted</b>.</li>}
        {plan.restore > 0 && <li>{plural(plan.restore, "balance")} it replaced will get their old amounts, notes and sources back.</li>}
        <li>Nothing else changes. Every other date in the account stays as it is.</li>
      </ul>
      <p className="sub">An undo cannot be undone, and an import can be undone only once. To bring the balances back, import the file again.</p>
      {error && <p className="notice bad" role="alert">{error}</p>}
      <div className="foot">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn danger" disabled={busy} autoFocus onClick={go}>Undo import</button>
      </div>
    </Modal>
  );
}

/** Asks what undoing would do and shows it, or why it cannot be done. Nothing is written until the person confirms. */
function UndoDialog({ entry, onDone, onClose }: { entry: ImportEntry; onDone: (done: UndoDone) => void; onClose: (changed: boolean) => void }) {
  const { data, error } = useRequest((signal) => fetchUndoPlan(entry.id, signal), [entry.id]);
  const [refusal, setRefusal] = useState<UndoRefusal | null>(null);
  const shown = refusal ?? (data !== null && "refused" in data ? data : null);
  const close = () => onClose(shown !== null);

  if (shown) return <Refused entry={entry} refusal={shown} onClose={close} />;
  if (data !== null && !("refused" in data)) {
    return <Confirm entry={entry} plan={data} onDone={onDone} onRefused={setRefusal} onClose={close} />;
  }
  return (
    <Modal title="Undo this import?" subtitle={describe(entry)} onClose={close}>
      {error ? <p className="notice bad" role="alert">{error}</p> : <p className="sub">Checking what undoing it would change&hellip;</p>}
      <div className="foot"><button className="btn ghost" onClick={close}>Close</button></div>
    </Modal>
  );
}

/** The admin page listing past imports, newest first, with Undo on the ones that have not been undone. */
export function Imports() {
  const { data, error, setData, reload } = useRequest(fetchImports, []);
  const [undoing, setUndoing] = useState<ImportEntry | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Imports</h1>
          <p className="sub">Balances imported from CSV files, newest first. Undo reverses an import that nothing has changed since.</p>
        </div>
      </div>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {notice && <p className="notice ok top-notice" role="status">{notice}</p>}
      {data && data.imports.length === 0 && (
        <p className="empty">No imports yet. Balances you import from a CSV file will be listed here.</p>
      )}
      {data && data.imports.length > 0 && (
        <>
          <div className="panel tablepanel">
            <table>
              <thead>
                <tr>
                  <th>Import Date</th><th>Import By</th><th>Account</th><th>File Name</th>
                  <th className="r">Added</th><th className="r">Replaced</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.imports.map((entry) => (
                  <tr key={entry.id}>
                    <td className="num">{entry.date}</td>
                    <td>{entry.by}</td>
                    <td><AccountCell entry={entry} /></td>
                    <td>{entry.file ?? "Unnamed file"}</td>
                    <td className="num r">{entry.added.toLocaleString("en-US")}</td>
                    <td className="num r">{entry.replaced.toLocaleString("en-US")}</td>
                    <td>
                      {entry.reverted_on !== null
                        ? <span className="reverted">Reverted on {entry.reverted_on}</span>
                        : <button className="btn ghost small" onClick={() => { setNotice(null); setUndoing(entry); }}>Undo&hellip;</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.more && <p className="sub">Showing the newest {plural(data.limit, "import")}. Older ones are not listed.</p>}
        </>
      )}
      {undoing && (
        <UndoDialog entry={undoing}
          onDone={(done) => {
            setData(done.after);
            setNotice(`Undid ${undoing.file ?? "the import"}: ${plural(done.deleted, "balance")} deleted and ${done.restored.toLocaleString("en-US")} restored.`);
            setUndoing(null);
          }}
          onClose={(changed) => { setUndoing(null); if (changed) reload(); }} />
      )}
    </div>
  );
}

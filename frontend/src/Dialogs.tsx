import { type ReactNode, useContext, useEffect, useState } from "react";
import { type Conflict, RequestError } from "./api";
import { RefreshMe } from "./session";

/** A box over the page. Escape or a click outside it closes it. */
export function Modal(props: { title: string; subtitle?: string; onClose: () => void; children: ReactNode }) {
  const { onClose } = props;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="card" role="dialog" aria-modal="true" aria-label={props.title}>
        <h2>{props.title}</h2>
        {props.subtitle && <p className="sub">{props.subtitle}</p>}
        {props.children}
      </div>
    </div>
  );
}

/** Runs an action that may be refused by the server, and keeps its message to show in the dialog. `conflict` is set when the
 *  refusal is that a balance changed since the person opened it, and `clear` forgets a refusal. */
export function useAction() {
  const refreshMe = useContext(RefreshMe);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setConflict(null);
    try {
      await action();
    } catch (e) {
      if (e instanceof RequestError && e.localeChanged) refreshMe(); // the draft stays, and is read in the new format
      const first = e instanceof RequestError ? e.conflicts[0] : undefined;
      if (first) setConflict(first);
      else setError((e as Error).message);
      setBusy(false); // on success the dialog is closed by the caller, so there is nothing to reset
    }
  };
  const clear = () => {
    setError(null);
    setConflict(null);
  };
  return { busy, error, conflict, run, clear };
}

/** A question that states the consequence, with Cancel and a confirming button. */
export function ConfirmDialog(props: {
  title: string;
  text: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
  onClose: () => void;
  /** For an action on a balance: what to say when it changed since the person opened it. Then only Close is offered, and `onConflict`
   *  lets the page behind show the balance as it is now. */
  conflict?: { lead: string; text: (conflict: Conflict) => string };
  onConflict?: () => void;
}) {
  const { busy, error, conflict, run } = useAction();
  const { onConflict } = props;
  useEffect(() => {
    if (conflict) onConflict?.();
  }, [conflict]); // eslint-disable-line react-hooks/exhaustive-deps -- once per refusal
  return (
    <Modal title={props.title} onClose={props.onClose}>
      <p className="sub">{props.text}</p>
      {error && <p className="notice bad" role="alert">{error}</p>}
      {conflict && props.conflict && <p className="notice bad" role="alert"><b>{props.conflict.lead}</b> {props.conflict.text(conflict)}</p>}
      <div className="foot">
        {conflict && props.conflict ? (
          <button className="btn" autoFocus onClick={props.onClose}>Close</button>
        ) : (
          <>
            <button className="btn ghost" onClick={props.onClose}>Cancel</button>
            <button className={props.danger ? "btn danger" : "btn"} disabled={busy} autoFocus onClick={() => run(props.onConfirm)}>
              {props.confirmLabel}
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}

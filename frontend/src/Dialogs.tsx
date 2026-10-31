import { type ReactNode, useEffect, useState } from "react";

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

/** Runs an action that may be refused by the server, and keeps its message to show in the dialog. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false); // on success the dialog is closed by the caller, so there is nothing to reset
    }
  };
  return { busy, error, run };
}

/** A question that states the consequence, with Cancel and a confirming button. */
export function ConfirmDialog(props: {
  title: string;
  text: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const { busy, error, run } = useAction();
  return (
    <Modal title={props.title} onClose={props.onClose}>
      <p className="sub">{props.text}</p>
      {error && <p className="notice bad" role="alert">{error}</p>}
      <div className="foot">
        <button className="btn ghost" onClick={props.onClose}>Cancel</button>
        <button className={props.danger ? "btn danger" : "btn"} disabled={busy} autoFocus onClick={() => run(props.onConfirm)}>
          {props.confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

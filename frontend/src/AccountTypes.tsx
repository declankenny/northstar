import { type FormEvent, useEffect, useState } from "react";
import { addType, deleteType, editType, fetchTypes, type TypeList, type TypeRow } from "./api";
import { ConfirmDialog, Modal, useAction } from "./Dialogs";

type Dialog = { kind: "edit"; type: TypeRow | null } | { kind: "delete"; type: TypeRow };

/** Add a type, or edit one. The class can change only while no account uses the type. */
function TypeDialog(props: { list: TypeList; editing: TypeRow | null; onSave: (t: { name: string; class_id: number; stale_after_days: number }) => Promise<void>; onClose: () => void }) {
  const { editing } = props;
  const [name, setName] = useState(editing?.name ?? "");
  const [classId, setClassId] = useState(editing?.class_id ?? props.list.classes[0].id);
  const [days, setDays] = useState(String(editing?.stale_after_days ?? 35));
  const { busy, error, run } = useAction();
  const locked = editing !== null && editing.account_count > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => props.onSave({ name, class_id: classId, stale_after_days: Number(days) }));
  };

  return (
    <Modal title={editing ? "Edit account type" : "Add account type"} onClose={props.onClose}>
      <form onSubmit={submit}>
        <label>Name
          <input value={name} placeholder="e.g. Savings" onChange={(e) => setName(e.target.value)} required autoFocus />
        </label>
        <label>Class
          <select value={classId} disabled={locked} onChange={(e) => setClassId(Number(e.target.value))}>
            {props.list.classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        {locked && <div className="hint">The class can't change while accounts use this type.</div>}
        <label>Stale after (days)
          <input type="number" min={1} step={1} value={days} onChange={(e) => setDays(e.target.value)} required />
        </label>
        <div className="hint">An account is flagged stale when its latest balance is older than this.</div>
        {error && <p className="notice bad" role="alert">{error}</p>}
        <div className="foot">
          <button type="button" className="btn ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{editing ? "Save" : "Add type"}</button>
        </div>
      </form>
    </Modal>
  );
}

function RowMenu(props: { type: TypeRow; onEdit: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const { type } = props;
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  const n = type.account_count;
  return (
    <>
      <button className={open ? "kebab on" : "kebab"} aria-label={`Actions for ${type.name}`} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>⋯</button>
      {open && (
        <div className="menu rowmenu" role="menu">
          <button role="menuitem" onClick={props.onEdit}>Edit</button>
          {/* A type in use can't be deleted, so the reason sits right after the word. */}
          <button role="menuitem" className="bad" disabled={n > 0} onClick={props.onDelete}>
            Delete{n > 0 && <span className="why"> ({n} {n === 1 ? "account uses" : "accounts use"} this type. Change {n === 1 ? "its" : "their"} type first.)</span>}
          </button>
        </div>
      )}
    </>
  );
}

export function AccountTypes() {
  const [list, setList] = useState<TypeList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);

  useEffect(() => {
    fetchTypes().then(setList, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="empty">Could not load account types. {error}</p>;
  if (!list) return <p className="empty">Loading…</p>;

  /** Every change answers with the list as it now is. */
  const apply = (fresh: TypeList) => { setList(fresh); setDialog(null); };

  return (
    <div className="acct">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Account types</h1>
          <p className="sub">Types group accounts and set how old a balance can be before the account is flagged stale.</p>
        </div>
        <button className="btn" onClick={() => setDialog({ kind: "edit", type: null })}>Add type</button>
      </div>

      <div className="stack">
        {list.classes.map((cls) => {
          const rows = list.types.filter((t) => t.class_id === cls.id);
          return (
            <div key={cls.id} className={`gcard ${cls.name.toLowerCase()}`}>
              <div className="gh">
                <span className="gt">{cls.name === "Asset" ? "Assets" : "Liabilities"}</span>
                <span className="m">{rows.length} {rows.length === 1 ? "type" : "types"}</span>
              </div>
              {rows.length === 0 ? (
                <p className="empty pad">No {cls.name.toLowerCase()} types yet.</p>
              ) : (
                <table className="num">
                  <colgroup><col style={{ width: "40%" }} /><col style={{ width: "22%" }} /><col style={{ width: "22%" }} /><col /></colgroup>
                  <thead>
                    <tr><th>Name</th><th className="r">Stale after (days)</th><th className="r">Accounts</th><th /></tr>
                  </thead>
                  <tbody>
                    {rows.map((t) => (
                      <tr key={t.id} className="row">
                        <td className="name">{t.name}</td>
                        <td className="r">{t.stale_after_days}</td>
                        <td className={t.account_count ? "r" : "r m"}>{t.account_count}</td>
                        <td className="k">
                          <RowMenu type={t} onEdit={() => setDialog({ kind: "edit", type: t })} onDelete={() => setDialog({ kind: "delete", type: t })} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>

      {dialog?.kind === "edit" && (
        <TypeDialog list={list} editing={dialog.type} onClose={() => setDialog(null)}
          onSave={async (t) => apply(dialog.type ? await editType(dialog.type.id, t) : await addType(t))} />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog title={`Delete ${dialog.type.name}?`} confirmLabel="Delete type" danger onClose={() => setDialog(null)}
          text="No account uses this type, so nothing else changes. This can't be undone."
          onConfirm={async () => apply(await deleteType(dialog.type.id))} />
      )}
    </div>
  );
}

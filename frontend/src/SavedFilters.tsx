import { useState } from "react";
import { changeSavedFilter, type Condition, deleteSavedFilter, fetchSavedFilters, type SavedFilter, type SavedFilters, saveSavedFilter } from "./api";
import { ConfirmDialog } from "./Dialogs";
import { sameConditions } from "./listFilters";
import { useRequest } from "./useRequest";
import type { FilterDraft } from "./useFilterDraft";

/** Saved filters, which only a list has: a report never renders this, so it never asks for them. They are kept per list, so they need
 *  the list's key. Choosing one only fills the draft, as if the conditions had been typed. */
export function useSavedFilters(listKey: string, openedWith: number | null, filters: FilterDraft) {
  const { nodes, draft, setDraft, valid, wire } = filters;
  const [loadedId, setLoadedId] = useState<number | null>(openedWith);
  const [picking, setPicking] = useState(false);
  const [form, setForm] = useState<{ mode: "new" | "rename"; name: string; shared: boolean; isDefault: boolean } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string | null>(null);

  const saved = useRequest((signal) => fetchSavedFilters(listKey, signal), [listKey]);
  const all = saved.data?.filters ?? [];
  const loaded = all.find((f) => f.id === loadedId) ?? null;
  const changed = loaded !== null && !sameConditions(draft, loaded.conditions.filter((c: Condition) => !loaded.problems.some((p) => p.field === c.field)), nodes);

  const choose = (filter: SavedFilter | null) => {
    setPicking(false); setForm(null); setMessage(null);
    setLoadedId(filter?.id ?? null);
    if (!filter) { setSkipped(null); return; }
    const gone = new Set(filter.problems.map((p) => p.field));
    setDraft(filter.conditions.filter((c) => !gone.has(c.field)));
    setSkipped(filter.problems.length === 0 ? null
      : `${filter.problems.length === 1 ? "1 condition was" : `${filter.problems.length} conditions were`} skipped: ${filter.problems.map((p) => p.field).join(", ")} ${filter.problems.length === 1 ? "is" : "are"} not offered by this list any more. Saving this filter drops ${filter.problems.length === 1 ? "it" : "them"}.`);
  };

  /** Runs a change to the saved filters, takes the answer as the new set, and says why when it was refused. */
  const change = async (action: () => Promise<SavedFilters>, then?: (answer: SavedFilters) => void) => {
    setBusy(true); setMessage(null);
    try {
      const answer = await action();
      saved.setData(answer);
      then?.(answer);
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const save = () => loaded && change(() => changeSavedFilter(listKey, loaded.id, { conditions: wire() }), () => setSkipped(null));
  const submitForm = () => {
    if (!form) return;
    if (form.mode === "rename" && loaded) return change(() => changeSavedFilter(listKey, loaded.id, { name: form.name }), () => setForm(null));
    return change(async () => {
      let answer = await saveSavedFilter(listKey, { name: form.name, conditions: wire(), shared: form.shared });
      const made = answer.filters.find((f) => f.shared === form.shared && f.name.toLowerCase() === form.name.trim().toLowerCase());
      if (made && form.isDefault) answer = await changeSavedFilter(listKey, made.id, { is_default: true });
      return answer;
    }, (answer) => {
      setForm(null); setSkipped(null);
      setLoadedId(answer.filters.find((f) => f.shared === form.shared && f.name.toLowerCase() === form.name.trim().toLowerCase())?.id ?? null);
    });
  };
  /** Clear filters empties the draft and lets go of the loaded saved filter. */
  const forget = () => { setLoadedId(null); setSkipped(null); };

  return { saved, all, loaded, changed, valid, picking, setPicking, form, setForm, deleting, setDeleting, busy, message, skipped, choose, change, save, submitForm, forget,
    empty: draft.length === 0, listKey, setLoadedId };
}

export type SavedFiltersState = ReturnType<typeof useSavedFilters>;

/** The saved-filter row at the top of a list's drawer: choose, save, save as new, rename, delete, and the defaults. */
export function SavedFiltersBar({ s, isAdmin }: { s: SavedFiltersState; isAdmin: boolean }) {
  const { saved, all, loaded, changed, valid, picking, setPicking, form, setForm, busy, message, skipped, choose, change, save, submitForm, listKey } = s;
  return (
    <div className="lf-saved">
      <span className="m">Saved filter</span>
      <button className="btn ghost small lf-pickbtn" aria-haspopup="menu" aria-expanded={picking} disabled={saved.loading && !saved.data}
        onClick={() => setPicking(!picking)}>
        {loaded ? loaded.name : "Choose…"}{loaded && changed && <span className="m"> · changed</span>} ▾</button>
      {picking && (
        <div className="menu lf-menu" role="menu">
          {all.some((f) => f.shared) && <div className="hint lf-group">Shared, for everyone</div>}
          {all.filter((f) => f.shared).map((f) => (
            <button key={f.id} role="menuitem" onClick={() => choose(f)}>{f.name}{f.is_default && <span className="m"> · default for everyone</span>}</button>
          ))}
          {all.some((f) => !f.shared) && <div className="hint lf-group">Mine</div>}
          {all.filter((f) => !f.shared).map((f) => (
            <button key={f.id} role="menuitem" onClick={() => choose(f)}>{f.name}{f.is_default && <span className="m"> · my default ★</span>}</button>
          ))}
          {all.length === 0 && <div className="hint lf-group">Nothing saved yet</div>}
          <hr /><button role="menuitem" onClick={() => choose(null)}>No saved filter</button>
        </div>
      )}
      <button className="link" disabled={busy || !loaded || !loaded.can_edit || !changed || !valid} onClick={save}>Save</button>
      <button className="link" disabled={busy || !valid || s.empty} onClick={() => setForm({ mode: "new", name: "", shared: false, isDefault: false })}>Save as new…</button>
      <button className="link" disabled={busy || !loaded || !loaded.can_edit} onClick={() => loaded && setForm({ mode: "rename", name: loaded.name, shared: loaded.shared, isDefault: false })}>Rename</button>
      <button className="link danger" disabled={busy || !loaded || !loaded.can_edit} onClick={() => s.setDeleting(true)}>Delete</button>
      {loaded && loaded.can_edit && (
        <label className="check m lf-default"><input type="checkbox" checked={loaded.is_default} disabled={busy}
          onChange={(e) => change(() => changeSavedFilter(listKey, loaded.id, { is_default: e.target.checked }))} />
          {loaded.shared ? "Default for everyone" : "My default"}</label>
      )}
      {skipped && <p className="hint lf-warn">{skipped}</p>}
      {saved.error && <p className="notice bad lf-wide" role="alert">Could not load the saved filters. {saved.error}</p>}
      {message && <p className="notice bad lf-wide" role="alert">{message}</p>}
      {form && (
        <div className="lf-form">
          <label className="m" htmlFor="lf-name">{form.mode === "new" ? "Name for the new filter" : "New name"}</label>
          <input id="lf-name" value={form.name} maxLength={80} autoFocus onChange={(e) => setForm({ ...form, name: e.target.value })} />
          {form.mode === "new" && isAdmin && (
            <label className="check m"><input type="checkbox" checked={form.shared} onChange={(e) => setForm({ ...form, shared: e.target.checked })} /> For everyone</label>
          )}
          {form.mode === "new" && (
            <label className="check m"><input type="checkbox" checked={form.isDefault} onChange={(e) => setForm({ ...form, isDefault: e.target.checked })} /> Make it my default</label>
          )}
          <div><button className="btn small" disabled={busy || form.name.trim() === ""} onClick={submitForm}>{form.mode === "new" ? "Save filter" : "Rename"}</button>{" "}
            <button className="link" onClick={() => setForm(null)}>Cancel</button></div>
        </div>
      )}
    </div>
  );
}

/** The question asked before a saved filter is deleted. It opens over the drawer, so it is the drawer's overlay. */
export function DeleteSavedFilter({ s }: { s: SavedFiltersState }) {
  const { loaded, deleting, setDeleting, saved, listKey, setLoadedId } = s;
  if (!deleting || !loaded) return null;
  return (
    <ConfirmDialog title={`Delete “${loaded.name}”?`} confirmLabel="Delete" danger
      text={loaded.shared ? "This filter is for everyone. It is removed for all of them. Lists already filtered by it keep their view." : "This saved filter is removed. The list keeps its current view."}
      onClose={() => setDeleting(false)}
      onConfirm={async () => { const answer = await deleteSavedFilter(listKey, loaded.id); saved.setData(answer); setLoadedId(null); setDeleting(false); }} />
  );
}

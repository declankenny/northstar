import { useEffect, useMemo, useRef, useState } from "react";
import {
  changeSavedFilter, type Choices, type Condition, deleteSavedFilter, fetchSavedFilters, type FieldNode, type FieldTree,
  type SavedFilter, type SavedFilters, saveSavedFilter,
} from "./api";
import { ColumnsPanel } from "./ColumnsPanel";
import { Combobox } from "./Combobox";
import { ConfirmDialog } from "./Dialogs";
import { FieldPicker } from "./FieldPicker";
import { columnChoice, sameColumns } from "./listColumns";
import {
  flatten, isDateKind, isNumberKind, isRange, isSingleChoice, problem, sameConditions, startCondition, takesNoValue, toWire, withOperator,
} from "./listFilters";
import { useRequest } from "./useRequest";

/** What the drawer needs from the list behind it. `choices` holds what a relation's records are called, once asked for. */
export type FilterDrawerProps = {
  listKey: string; title: string; tree: FieldTree; applied: Condition[];
  openedWith: number | null;                       // the saved filter the list opened with, so it shows as loaded
  isAdmin: boolean;                                // admins can save a filter for everyone
  choices: Map<string, Choices>; ensureChoices: (field: string) => void;
  columns: string[];                               // the keys of the columns the list shows now
  defaultColumns: string[];                        // and of the ones it shows when a person has chosen none
  skippedColumns: string[];                        // saved columns the list no longer offers, left out of `columns`
  tab: "filters" | "columns";                      // the tab the drawer opens on
  /** `columns` is what the server is to be told: nothing (undefined) when they are as they were, null to forget the choice. */
  onApply: (conditions: Condition[], columns: string[] | null | undefined) => void; onClose: () => void;
};

/** One choice among a declared set or the records the list points at, with check boxes: several together mean "any of". */
function ChoiceBox({ node, value, choices, onChange }: { node: FieldNode; value: unknown[]; choices?: Choices; onChange: (next: unknown[]) => void }) {
  const options = node.choices === "values"
    ? (node.values ?? []).map((v) => ({ id: v as string | number, label: v, detail: null as string | null }))
    : (choices?.options ?? []).map((o) => ({ id: o.id as string | number, label: o.value, detail: o.detail }));
  const toggle = (id: string | number) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  if (node.choices === "records" && !choices) return <span className="hint">Loading the choices…</span>;
  return (
    <div className="lf-choices" role="group" aria-label={`Values for ${node.path_label}`}>
      {options.map((o) => (
        <label key={String(o.id)} className="check"><input type="checkbox" checked={value.includes(o.id)} onChange={() => toggle(o.id)} />
          {o.label}{o.detail && <span className="m"> · {o.detail}</span>}</label>
      ))}
      {options.length === 0 && <span className="hint">Nothing to choose from.</span>}
      {choices?.more && <span className="hint">Only the first {options.length} are listed.</span>}
    </div>
  );
}

/** One choice among a declared set or the records the list points at, found by typing. The choice is an id for a record and the value
 *  itself for a declared set. */
function ChoiceSelect({ node, value, choices, onChange }: { node: FieldNode; value: unknown; choices?: Choices; onChange: (next: unknown) => void }) {
  if (node.choices === "records" && !choices) return <span className="hint">Loading the choices…</span>;
  const options = node.choices === "values"
    ? (node.values ?? []).map((v) => ({ id: v as string | number, label: v, detail: null as string | null }))
    : (choices?.options ?? []).map((o) => ({ id: o.id as string | number, label: o.value, detail: o.detail }));
  return (
    <>
      <Combobox options={options} value={typeof value === "string" || typeof value === "number" ? value : ""} onChange={onChange}
        label={`Value for ${node.path_label}`} placeholder="Search" />
      {choices?.more && <span className="hint">Only the first {options.length} are listed.</span>}
    </>
  );
}

function ValueInputs({ node, condition, choices, onChange }: { node: FieldNode; condition: Condition; choices?: Choices; onChange: (value: unknown) => void }) {
  const { operator, value } = condition;
  if (takesNoValue(operator)) return null;
  if (node.choices !== null && isSingleChoice(operator)) return <ChoiceSelect node={node} value={value} choices={choices} onChange={onChange} />;
  if (node.choices !== null) return <ChoiceBox node={node} value={Array.isArray(value) ? value : []} choices={choices} onChange={onChange} />;
  const type = isDateKind(node.kind) ? "date" : "text";
  const mode = isNumberKind(node.kind) ? "decimal" : undefined;
  const one = (text: unknown, set: (next: string) => void, label: string) => (
    <input type={type} inputMode={mode} aria-label={label} value={String(text ?? "")} maxLength={type === "date" ? undefined : 256}
      onChange={(e) => set(e.target.value)} />
  );
  if (isRange(operator)) {
    const pair = Array.isArray(value) ? value : ["", ""];
    return (
      <>
        {one(pair[0], (next) => onChange([next, pair[1]]), `${node.path_label}, from`)}
        <span className="m">and</span>
        {one(pair[1], (next) => onChange([pair[0], next]), `${node.path_label}, to`)}
      </>
    );
  }
  return one(value, onChange, node.path_label);
}

/** Something has been put into the condition, so a mistake in it is worth saying at once; an empty new row is not nagged. */
const typedIn = ({ value }: Condition) => (Array.isArray(value) ? value.some((v) => v !== "") : typeof value === "string" && value.trim() !== "");

function ConditionRow({ node, condition, error, choices, onChange, onRemove }: {
  node: FieldNode | undefined; condition: Condition; error: string | null; choices?: Choices;
  onChange: (next: Condition) => void; onRemove: () => void;
}) {
  if (!node) {
    return (
      <div className="lf-cond">
        <div className="lf-row"><span>{condition.field}</span><span className="m">not a column of this list</span><span />
          <button className="lf-x" aria-label={`Remove the filter on ${condition.field}`} onClick={onRemove}>✕</button></div>
      </div>
    );
  }
  return (
    <div className="lf-cond">
      <div className="lf-row">
        <span>{node.path_label}</span>
        <select aria-label={`How to compare ${node.path_label}`} value={condition.operator}
          onChange={(e) => onChange(withOperator(node, condition, e.target.value))}>
          {node.operators.map((o) => <option key={o.name} value={o.name}>{o.label}</option>)}
        </select>
        <div className="vals"><ValueInputs node={node} condition={condition} choices={choices}
          onChange={(value) => onChange({ field: condition.field, operator: condition.operator, value })} /></div>
        <button className="lf-x" aria-label={`Remove the filter on ${node.path_label}`} onClick={onRemove}>✕</button>
      </div>
      {error && <p className="notice bad lf-err" role="alert">{error}</p>}
    </div>
  );
}

/** The drawer where a list's filters are made, applied and saved. What is typed here is a draft: nothing reaches the list until
 *  Apply changes, and Cancel throws it away. Choosing a saved filter only fills the draft, as if the conditions had been typed. */
export function FilterDrawer(props: FilterDrawerProps) {
  const { listKey, title, tree, applied, openedWith, isAdmin, choices, ensureChoices, columns, defaultColumns, skippedColumns, onApply, onClose } = props;
  const [tab, setTab] = useState(props.tab);
  const [draftColumns, setColumns] = useState(columns);
  const touched = useRef(false);                       // the person has changed the columns, so a later answer from the list must not undo it
  const setDraftColumns = (next: string[]) => { touched.current = true; setColumns(next); };
  useEffect(() => { if (!touched.current) setColumns(columns); }, [columns]);   // the list had not answered yet when the drawer opened
  const nodes = useMemo(() => new Map(flatten(tree).map((n) => [n.key, n])), [tree]);
  const [draft, setDraft] = useState<Condition[]>(applied);
  const [loadedId, setLoadedId] = useState<number | null>(openedWith);
  const [adding, setAdding] = useState(false);
  const [picking, setPicking] = useState(false);
  const [form, setForm] = useState<{ mode: "new" | "rename"; name: string; shared: boolean; isDefault: boolean } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);       // Apply was pressed with something incomplete: now every gap is pointed out
  const box = useRef<HTMLDivElement>(null);

  const saved = useRequest((signal) => fetchSavedFilters(listKey, signal), [listKey]);
  const filters = saved.data?.filters ?? [];
  const loaded = filters.find((f) => f.id === loadedId) ?? null;

  useEffect(() => { box.current?.focus(); }, []);
  useEffect(() => { draft.forEach((c) => { if (nodes.get(c.field)?.choices === "records") ensureChoices(c.field); }); }, [draft, nodes, ensureChoices]);

  const errors = draft.map((c) => { const node = nodes.get(c.field); return node ? problem(node, c) : "That is not a column of this list any more."; });
  const valid = errors.every((e) => e === null);
  const changed = loaded !== null && !sameConditions(draft, loaded.conditions.filter((c) => !loaded.problems.some((p) => p.field === c.field)), nodes);
  const wire = () => draft.map((c) => toWire(nodes.get(c.field), c));

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

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape" && !deleting) { event.stopPropagation(); onClose(); }
  };
  const used = new Set(draft.map((c) => c.field));

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={`${title} filters`} tabIndex={-1} ref={box} onKeyDown={onKey}>
      <div className="drawer-head"><h2>{title} view</h2><button className="kebab" aria-label="Close" onClick={onClose}>✕</button></div>
      <div className="ranges lf-tabs">
        <button className={tab === "filters" ? "on" : ""} aria-current={tab === "filters" ? "true" : undefined} onClick={() => setTab("filters")}>Filters ({draft.length})</button>
        <button className={tab === "columns" ? "on" : ""} aria-current={tab === "columns" ? "true" : undefined} disabled={columns.length === 0}
          onClick={() => setTab("columns")}>Columns ({draftColumns.length})</button>
      </div>
      <div className="drawer-body">
        {tab === "columns" && <ColumnsPanel tree={tree} keys={draftColumns} skipped={skippedColumns} onChange={setDraftColumns} />}
        {tab === "filters" && <>
        <div className="lf-saved">
          <span className="m">Saved filter</span>
          <button className="btn ghost small lf-pickbtn" aria-haspopup="menu" aria-expanded={picking} disabled={saved.loading && !saved.data}
            onClick={() => setPicking(!picking)}>
            {loaded ? loaded.name : "Choose…"}{loaded && changed && <span className="m"> · changed</span>} ▾</button>
          {picking && (
            <div className="menu lf-menu" role="menu">
              {filters.some((f) => f.shared) && <div className="hint lf-group">Shared, for everyone</div>}
              {filters.filter((f) => f.shared).map((f) => (
                <button key={f.id} role="menuitem" onClick={() => choose(f)}>{f.name}{f.is_default && <span className="m"> · default for everyone</span>}</button>
              ))}
              {filters.some((f) => !f.shared) && <div className="hint lf-group">Mine</div>}
              {filters.filter((f) => !f.shared).map((f) => (
                <button key={f.id} role="menuitem" onClick={() => choose(f)}>{f.name}{f.is_default && <span className="m"> · my default ★</span>}</button>
              ))}
              {filters.length === 0 && <div className="hint lf-group">Nothing saved yet</div>}
              <hr /><button role="menuitem" onClick={() => choose(null)}>No saved filter</button>
            </div>
          )}
          <button className="link" disabled={busy || !loaded || !loaded.can_edit || !changed || !valid} onClick={save}>Save</button>
          <button className="link" disabled={busy || !valid || draft.length === 0} onClick={() => setForm({ mode: "new", name: "", shared: false, isDefault: false })}>Save as new…</button>
          <button className="link" disabled={busy || !loaded || !loaded.can_edit} onClick={() => loaded && setForm({ mode: "rename", name: loaded.name, shared: loaded.shared, isDefault: false })}>Rename</button>
          <button className="link danger" disabled={busy || !loaded || !loaded.can_edit} onClick={() => setDeleting(true)}>Delete</button>
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

        {draft.length === 0 && <p className="hint">No conditions. Every row is shown.</p>}
        {attempted && !valid && <p className="notice bad" role="alert">Complete or remove the conditions marked below, then apply.</p>}
        {draft.map((condition, i) => (
          <ConditionRow key={condition.field} node={nodes.get(condition.field)} condition={condition} error={attempted || typedIn(condition) ? errors[i] : null}
            choices={choices.get(condition.field)}
            onChange={(next) => setDraft(draft.map((c, j) => (j === i ? next : c)))}
            onRemove={() => setDraft(draft.filter((_, j) => j !== i))} />
        ))}
        <button className="link" aria-expanded={adding} onClick={() => setAdding(!adding)}>+ Add filter</button>
        {adding && <FieldPicker tree={tree} used={used} label="Columns to filter by" usedNote="already filtered" unavailable={(node) => node.operators.length === 0}
          onPick={(node) => { setDraft([...draft, startCondition(node)]); setAdding(false); }} />}
        <p className="hint lf-help">Conditions combine with AND; several choices in one condition mean any of them. “is after” leaves out the date itself; “is between” includes both ends. Amounts are compared in each row’s own currency, so filter by Currency too when comparing across currencies.</p>
        </>}
      </div>
      <div className="drawer-foot">
        {tab === "filters"
          ? <button className="link" onClick={() => { setDraft([]); setLoadedId(null); setSkipped(null); }}>Clear filters</button>
          : <button className="link" disabled={sameColumns(draftColumns, defaultColumns)} onClick={() => setDraftColumns(defaultColumns)}>Reset to default columns</button>}
        <span className="grow" />
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={() => (valid ? onApply(wire(), columns.length === 0 ? undefined : columnChoice(draftColumns, columns, defaultColumns)) : (setAttempted(true), setTab("filters")))}>Apply changes</button>
      </div>
      {deleting && loaded && (
        <ConfirmDialog title={`Delete “${loaded.name}”?`} confirmLabel="Delete" danger
          text={loaded.shared ? "This filter is for everyone. It is removed for all of them. Lists already filtered by it keep their view." : "This saved filter is removed. The list keeps its current view."}
          onClose={() => setDeleting(false)}
          onConfirm={async () => { const answer = await deleteSavedFilter(listKey, loaded.id); saved.setData(answer); setLoadedId(null); setDeleting(false); }} />
      )}
    </div>
  );
}

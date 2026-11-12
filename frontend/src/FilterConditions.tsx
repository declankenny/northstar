import { useState } from "react";
import type { Choices, Condition, FieldNode, FieldTree } from "./api";
import { Combobox } from "./Combobox";
import { FieldPicker } from "./FieldPicker";
import type { FilterWords } from "./filterWords";
import { isDateKind, isNumberKind, isRange, isSingleChoice, startCondition, takesNoValue, withOperator } from "./listFilters";
import type { FilterDraft } from "./useFilterDraft";

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

function ConditionRow({ node, condition, gone, error, choices, onChange, onRemove }: {
  node: FieldNode | undefined; condition: Condition; gone: string; error: string | null; choices?: Choices;
  onChange: (next: Condition) => void; onRemove: () => void;
}) {
  if (!node) {
    return (
      <div className="lf-cond">
        <div className="lf-row"><span>{condition.field}</span><span className="m">{gone}</span><span />
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

/** The conditions of a draft, one row each, with the way to add another and the note on how they combine. The same for a list and
 *  for a report: only the words differ. `choices` holds what a relation's records are called, once asked for. */
export function FilterConditions({ tree, filters, choices, words }: { tree: FieldTree; filters: FilterDraft; choices: Map<string, Choices>; words: FilterWords }) {
  const { nodes, draft, setDraft, errors, valid, attempted } = filters;
  const [adding, setAdding] = useState(false);
  const used = new Set(draft.map((c) => c.field));
  return (
    <>
      {draft.length === 0 && <p className="hint">{words.empty}</p>}
      {attempted && !valid && <p className="notice bad" role="alert">Complete or remove the conditions marked below, then apply.</p>}
      {draft.map((condition, i) => (
        <ConditionRow key={condition.field} node={nodes.get(condition.field)} condition={condition} gone={words.gone}
          error={attempted || typedIn(condition) ? errors[i] : null} choices={choices.get(condition.field)}
          onChange={(next) => setDraft(draft.map((c, j) => (j === i ? next : c)))}
          onRemove={() => setDraft(draft.filter((_, j) => j !== i))} />
      ))}
      <button className="link" aria-expanded={adding} onClick={() => setAdding(!adding)}>+ Add filter</button>
      {adding && <FieldPicker tree={tree} used={used} label={words.picker} things={words.things} usedNote="already filtered" unavailable={(node) => node.operators.length === 0}
        onPick={(node) => { setDraft([...draft, startCondition(node)]); setAdding(false); }} />}
      <p className="hint lf-help">{words.help}</p>
    </>
  );
}

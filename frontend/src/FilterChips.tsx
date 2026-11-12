import type { Choices, Condition, FieldNode } from "./api";
import { describe } from "./listFilters";

/** What is applied, one removable chip per condition, with a way to clear them all. Says nothing when nothing is applied. `names`
 *  holds what a relation's ids stand for, by field. */
export function FilterChips({ conditions, nodes, names, onRemove, onClear }: {
  conditions: Condition[]; nodes: Map<string, FieldNode>; names: Map<string, Choices>;
  onRemove: (index: number) => void; onClear: () => void;
}) {
  if (conditions.length === 0) return null;
  return (
    <div className="lf-chips" role="list" aria-label="Filters applied">
      {conditions.map((condition, i) => {
        const text = describe(nodes.get(condition.field), condition, names.get(condition.field));
        return (
          <span className="lf-chip" role="listitem" key={condition.field}>
            {text}
            <button aria-label={`Remove the filter: ${text}`} onClick={() => onRemove(i)}>✕</button>
          </span>
        );
      })}
      <button className="link" onClick={onClear}>Clear filters</button>
    </div>
  );
}

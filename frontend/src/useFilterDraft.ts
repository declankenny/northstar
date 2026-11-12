import { useEffect, useMemo, useState } from "react";
import type { Condition, FieldNode, FieldTree } from "./api";
import { flatten, problem, toWire } from "./listFilters";

/** A condition on a field that is not offered any more cannot be applied. Only its being refused matters: the row says so itself. */
const NOT_OFFERED = "Not offered any more.";

/** The draft behind a filter drawer: what is typed here reaches nothing until Apply. It starts from what is applied, says what is wrong
 *  with each condition (null when complete), and knows how the whole is written for the server. `attempted` is set when Apply was
 *  pressed with something incomplete, and from then on every gap is pointed out. */
export function useFilterDraft(tree: FieldTree, applied: Condition[], ensureChoices: (field: string) => void) {
  const nodes = useMemo(() => new Map(flatten(tree).map((n): [string, FieldNode] => [n.key, n])), [tree]);
  const [draft, setDraft] = useState<Condition[]>(applied);
  const [attempted, setAttempted] = useState(false);
  useEffect(() => { draft.forEach((c) => { if (nodes.get(c.field)?.choices === "records") ensureChoices(c.field); }); }, [draft, nodes, ensureChoices]);
  const errors = draft.map((c) => { const node = nodes.get(c.field); return node ? problem(node, c) : NOT_OFFERED; });
  const valid = errors.every((e) => e === null);
  const wire = () => draft.map((c) => toWire(nodes.get(c.field), c));
  return { nodes, draft, setDraft, errors, valid, attempted, setAttempted, wire };
}

export type FilterDraft = ReturnType<typeof useFilterDraft>;

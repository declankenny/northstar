import { useCallback, useEffect, useRef, useState } from "react";
import type { Choices, Condition, FieldNode } from "./api";

/** What a relation's records are called, for chips and the filter drawer: a condition holds ids, and the person is shown names.
 *  The names are asked for once per field, the first time something needs them, from `fetchChoices` (a list's or a report's own
 *  endpoint). `scope` says which list or report this is: another scope starts afresh. Conditions that are already applied get their
 *  names without anyone opening the drawer. */
export function useChoiceNames(scope: string, fetchChoices: (field: string) => Promise<Choices>, applied: Condition[], nodes: Map<string, FieldNode>) {
  const [named, setNamed] = useState<Map<string, Choices>>(new Map());
  const asked = useRef(new Set<string>());
  const fetcher = useRef(fetchChoices);
  fetcher.current = fetchChoices;
  const ensureChoices = useCallback((field: string) => {
    const id = `${scope}/${field}`;
    if (asked.current.has(id)) return;
    asked.current.add(id);
    fetcher.current(field).then(
      (choices) => setNamed((before) => new Map(before).set(field, choices)),
      () => asked.current.delete(id),
    );
  }, [scope]);
  useEffect(() => { asked.current = new Set(); setNamed(new Map()); }, [scope]);
  useEffect(() => { applied.forEach((c) => { if (nodes.get(c.field)?.choices === "records") ensureChoices(c.field); }); }, [applied, nodes, ensureChoices]);
  return { named, ensureChoices };
}

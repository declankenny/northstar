import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import type { HierarchyNode } from "./types";

/** Which parents of a hierarchy a person has flipped from the way their section starts (open or closed, as the section says). One state is shared
 *  by every view of a report on the page, keyed by node id, so a report that shows the same nodes as a chart and as a table shows them open
 *  and closed together: opening a type in one opens it in the other. A node that is not in a view is simply not shown there. */
export type Expansion = {
  flipped: ReadonlySet<string>;
  flip: (id: string) => void;
  /** Replace what is flipped. */
  set: (ids: ReadonlySet<string>) => void;
};

function useExpansionState(): Expansion {
  const [flipped, setFlipped] = useState<ReadonlySet<string>>(new Set());
  const flip = useCallback((id: string) => setFlipped((before) => { const next = new Set(before); if (next.has(id)) next.delete(id); else next.add(id); return next; }), []);
  return useMemo(() => ({ flipped, flip, set: setFlipped }), [flipped, flip]);
}

const Shared = createContext<Expansion | null>(null);

/** The state a report's views share. A report page puts one around its sections. */
export function ExpansionProvider({ children }: { children: ReactNode }) {
  return <Shared.Provider value={useExpansionState()}>{children}</Shared.Provider>;
}

/** The state a view uses: the report's shared one, or its own when it is not inside a report (a view on its own page, or a test). */
export function useExpansion(): Expansion {
  const own = useExpansionState();
  return useContext(Shared) ?? own;
}

/** The ids of the nodes that have nodes inside them, at any depth. */
export function parentIds(nodes: HierarchyNode[]): string[] {
  return nodes.flatMap((node) => (node.children?.length ? [node.id, ...parentIds(node.children)] : []));
}

/** What to flip so every parent is open (`open`) or every parent is closed, for a section that starts `expanded` or not. */
export function allFlipped(nodes: HierarchyNode[], startsExpanded: boolean, open: boolean): ReadonlySet<string> {
  return open === startsExpanded ? new Set() : new Set(parentIds(nodes));
}

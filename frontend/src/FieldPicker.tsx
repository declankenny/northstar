import { type ReactNode, useState } from "react";
import type { FieldNode, FieldTree } from "./api";

/** The columns a list offers (`things` is what a report calls them), as a tree to choose one from: the list's own, and under each relation the columns of what it points
 *  at. A column in `used` is shown but cannot be chosen again; `unavailable` greys out one that cannot be chosen at all. `usedNote`
 *  says why a used one is greyed, when the words help (the column drawer's needs none, because its list already shows the column). */
export function FieldPicker({ tree, used, label, things = "columns", usedNote, unavailable, onPick }: {
  tree: FieldTree; used: Set<string>; label: string; things?: string; usedNote?: string; unavailable?: (node: FieldNode) => boolean; onPick: (node: FieldNode) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const note = (node: FieldNode) => used.has(node.key) && usedNote && <span className="m"> · {usedNote}</span>;
  const leaf = (node: FieldNode) => (
    <li key={node.key}>
      <span className="lf-pick-row">
        <button className="link" disabled={used.has(node.key) || !!unavailable?.(node)} onClick={() => onPick(node)}>{node.label}</button>
        {note(node)}
      </span>
    </li>
  );
  const list = (level: FieldTree): ReactNode => (
    <ul className="lf-pick">
      {level.fields.map(leaf)}
      {level.relations.map((node) => {
        const expandable = !!node.children;
        const isOpen = open.has(node.key);
        const toggle = expandable && (
          <button className="lf-fold" aria-expanded={isOpen} aria-label={`${isOpen ? "Hide" : "Show"} the ${things} of ${node.label}`}
            onClick={() => setOpen((before) => { const next = new Set(before); if (isOpen) next.delete(node.key); else next.add(node.key); return next; })}>
            {isOpen ? "▾" : "▸"}</button>
        );
        return (
          <li key={node.key}>
            <span className="lf-pick-row">
              {toggle}
              <button className="link" disabled={used.has(node.key)} onClick={() => onPick(node)}>{node.label}</button>
              {note(node)}
            </span>
            {expandable && isOpen && list(node.children!)}
          </li>
        );
      })}
    </ul>
  );
  return <div className="lf-picker" aria-label={label}>{list(tree)}</div>;
}

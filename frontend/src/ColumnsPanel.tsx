import {
  closestCenter, DndContext, type Announcements, type DragEndEvent, KeyboardSensor, PointerSensor, useSensor, useSensors,
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useEffect, useMemo, useState } from "react";
import type { FieldNode, FieldTree } from "./api";
import { FieldPicker } from "./FieldPicker";
import { moved } from "./listColumns";
import { flatten } from "./listFilters";

/** A column's name and, in small type, the relation it is reached through: "Name" beside "Account". */
function names(node: FieldNode | undefined, key: string): { name: string; path: string } {
  if (!node) return { name: key, path: "" };
  const path = node.path_label.endsWith(node.label) ? node.path_label.slice(0, node.path_label.length - node.label.length).replace(/ › $/, "") : "";
  return { name: node.label, path };
}

function Row({ id, index, count, node, added, onMove, onRemove }: {
  id: string; index: number; count: number; node: FieldNode | undefined; added: boolean; onMove: (to: number) => void; onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id });
  const { name, path } = names(node, id);
  const full = node?.path_label ?? id;
  return (
    <li ref={setNodeRef} className={isDragging ? "lc-item lifted" : added ? "lc-item added" : "lc-item"} style={{ transform: CSS.Transform.toString(transform), transition }}>
      <button ref={setActivatorNodeRef} className="lc-handle" aria-label={`Drag ${full} to move it`} {...attributes} {...listeners}>⠿</button>
      <span className="lc-name">{name}{path && <small>{path}</small>}</span>
      <button className="lc-arrow" aria-label={`Move ${full} up`} disabled={index === 0} onClick={() => onMove(index - 1)}>↑</button>
      <button className="lc-arrow" aria-label={`Move ${full} down`} disabled={index === count - 1} onClick={() => onMove(index + 1)}>↓</button>
      <button className="lf-x" aria-label={`Remove ${full}`} disabled={count === 1} title={count === 1 ? "At least one column stays" : undefined}
        onClick={onRemove}>✕</button>
    </li>
  );
}

/** The columns a list shows, in order. A draft, like the filters: nothing changes until the drawer is applied. A column is moved by
 *  dragging its handle or by the arrows, and the list always keeps at least one. */
export function ColumnsPanel({ tree, keys, skipped, onChange }: { tree: FieldTree; keys: string[]; skipped: string[]; onChange: (next: string[]) => void }) {
  const nodes = useMemo(() => new Map(flatten(tree).map((n) => [n.key, n])), [tree]);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);        // the column just added, said until the picker closes or anything else changes
  const [flash, setFlash] = useState(false);                       // and its row shown for a moment
  useEffect(() => {
    if (added === null) return;
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), 1500);
    return () => window.clearTimeout(timer);
  }, [added]);
  const label = (id: string | number) => nodes.get(String(id))?.path_label ?? String(id);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),   // a click on the handle is not a drag
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const position = (id: string | number) => keys.indexOf(String(id)) + 1;
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${label(active.id)}. Position ${position(active.id)} of ${keys.length}. Arrow keys move it, Space drops it, Escape puts it back.`,
    onDragOver: ({ active, over }) => (over ? `${label(active.id)} is over position ${position(over.id)} of ${keys.length}.` : `${label(active.id)} is not over a position.`),
    onDragEnd: ({ active, over }) => (over ? `Dropped ${label(active.id)} at position ${position(over.id)} of ${keys.length}.` : `Dropped ${label(active.id)} where it was.`),
    onDragCancel: ({ active }) => `Moving ${label(active.id)} was cancelled. It stays at position ${position(active.id)} of ${keys.length}.`,
  };
  const change = (next: string[]) => { setAdded(null); onChange(next); };      // anything but an addition ends what was said about the last one
  const onDragEnd = ({ active, over }: DragEndEvent) => { if (over) change(moved(keys, keys.indexOf(String(active.id)), keys.indexOf(String(over.id)))); };

  return (
    <>
      <p className="lc-add"><button className="link" aria-expanded={adding} onClick={() => { setAdding(!adding); setAdded(null); }}>+ Add column</button></p>
      {adding && <FieldPicker tree={tree} used={new Set(keys)} label="Columns to show" onPick={(node) => { onChange([...keys, node.key]); setAdded(node.key); }} />}
      {adding && added !== null && keys.includes(added) && <p className="hint" role="status">“{label(added)}” added at the end of the list.</p>}
      {skipped.length > 0 && (
        <p className="notice warn" role="status">
          {skipped.map((k) => `“${label(k)}”`).join(", ")} {skipped.length === 1 ? "is" : "are"} not offered by this list any more, so {skipped.length === 1 ? "it was" : "they were"} left
          out of your columns. Applying saves the columns without {skipped.length === 1 ? "it" : "them"}.</p>
      )}
      <p className="hint">Columns appear in this order. Drag a row by its handle, or use the arrows.</p>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} accessibility={{ announcements }}>
        <SortableContext items={keys} strategy={verticalListSortingStrategy}>
          <ol className="lc-list" aria-label="Columns shown">
            {keys.map((key, i) => (
              <Row key={key} id={key} index={i} count={keys.length} node={nodes.get(key)} added={flash && key === added}
                onMove={(to) => change(moved(keys, i, to))} onRemove={() => change(keys.filter((k) => k !== key))} />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      {keys.length === 1 && <p className="hint">At least one column stays, so the list is never empty.</p>}
    </>
  );
}

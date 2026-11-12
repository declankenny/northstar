import { useEffect, useMemo, useRef, useState } from "react";
import { Chart, type ChartClick } from "./Chart";
import { useChartTheme } from "./theme";
import { slotOf, type TreeNode, trailOf, treemapOption } from "./treemap";

/** A treemap you can drill into, and the same data as buttons. Clicking a block, or its button in the list, shows what is inside it; the
 *  breadcrumb goes back up. The chart is a picture: its marks cannot be reached by keyboard, so everything it can do, the list and the
 *  breadcrumb do. Drilling or going back removes the button that was focused, so focus moves to where you now are (the current place in the
 *  breadcrumb), and Tab from there reaches what is inside it. A node with nothing inside it calls `onLeaf` (a report opens the record it stands for). `format` says a node's value. */
export function TreemapDrill({ root, format, label, onLeaf }: { root: TreeNode; format: (node: TreeNode) => string; label: string; onLeaf?: (node: TreeNode) => void }) {
  const theme = useChartTheme();
  const [path, setPath] = useState<string[]>([]);
  const trail = useMemo(() => trailOf(root, path), [root, path]);
  const focus = trail[trail.length - 1];
  const nodes = useMemo(() => focus.children ?? [], [focus]);
  const option = useMemo(() => treemapOption(nodes, trail, theme, format), [nodes, trail, theme, format]);

  const here = useRef<HTMLSpanElement>(null);
  const moved = useRef(false);                       // a control of the page took us somewhere, so focus follows (a click on the chart does not take it)
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    here.current?.focus();
  }, [path]);

  const go = (next: string[]) => { moved.current = true; setPath(next); };
  const open = (node: TreeNode, byControl = true) => {
    if (!node.children?.length) return onLeaf?.(node);
    const next = [...trail.slice(1).map((n) => n.id), node.id];
    if (byControl) go(next); else setPath(next);
  };
  const clicked = ({ data }: ChartClick) => {
    const id = (data as { id?: string } | undefined)?.id;
    const node = nodes.find((n) => n.id === id);
    if (node) open(node, false);
  };

  return (
    <div className="chart-frame">
      <nav className="chart-crumbs" aria-label={`Where you are in ${label}`}>
        {trail.map((node, i) => (
          <span key={node.id}>
            {i > 0 && <span className="m" aria-hidden="true"> › </span>}
            {i < trail.length - 1
              ? <button className="link" onClick={() => go(trail.slice(1, i + 1).map((n) => n.id))}>{node.name}</button>
              : <span aria-current="location" tabIndex={-1} ref={here}>{node.name}</span>}
          </span>
        ))}
      </nav>
      <Chart option={option} label={`${label}: ${focus.name}`} onClick={clicked} />
      <ul className="chart-list" aria-label={`${label}, as a list`}>
        {nodes.map((node) => {
          const slot = slotOf(node, trail);
          return (
            <li key={node.id}>
              <button className="chart-item" onClick={() => open(node)}>
                <span className={`chart-swatch${slot ? ` chart-slot-${slot}` : ""}`} aria-hidden="true" />
                <span className="chart-item-name">{node.name}{node.children?.length ? <span className="m"> ▸</span> : null}</span>
                <span className="num">{format(node)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

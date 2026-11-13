import { useEffect, useMemo, useRef, useState } from "react";
import { Chart, type ChartClick } from "./Chart";
import { echarts } from "./echarts";
import { useChartTheme } from "./theme";
import { isDrawn, slotOf, tooLittleRoom, type TreeNode, trailOf, treemapOption } from "./treemap";

/** A treemap you can drill into, and the same data as buttons. Clicking a block, or its button in the list, shows what is inside it; the
 *  breadcrumb goes back up. The chart is a picture: its marks cannot be reached by keyboard, so everything it can do, the list and the
 *  breadcrumb do. Drilling or going back removes the button that was focused, so focus moves to where you now are (the current place in the
 *  breadcrumb), and Tab from there reaches what is inside it. A node with nothing inside it calls `onLeaf` (a report opens the record it stands for). `format` says a node's value.
 *
 *  A block cannot be negative or empty, so a node with no area (`size` 0) is kept in the list, last where the report put it, marked "not in the chart",
 *  and is not drawn, and its note is in the list too, since the tooltip has no block to hang it on. A block too small to hold its label shows none: the list and the tooltip still name it. Nothing inside the node drilled into
 *  draws no chart and no list, and the caller says why (a note on its section). */
export function TreemapDrill({ root, format, label, onLeaf }: { root: TreeNode; format: (node: TreeNode) => string; label: string; onLeaf?: (node: TreeNode) => void }) {
  const theme = useChartTheme();
  const [path, setPath] = useState<string[]>([]);
  const trail = useMemo(() => trailOf(root, path), [root, path]);
  const focus = trail[trail.length - 1];
  const nodes = useMemo(() => focus.children ?? [], [focus]);
  const drawn = useMemo(() => nodes.filter(isDrawn), [nodes]);
  const [unlabelled, setUnlabelled] = useState<string[]>([]);            // blocks too small for a label, found from the layout ECharts worked out
  const option = useMemo(() => treemapOption(nodes, trail, theme, format, new Set(unlabelled)), [nodes, trail, theme, format, unlabelled]);

  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = frame.current?.querySelector<HTMLElement>(".chart-canvas");
    if (!el) return;
    // Which blocks have room depends on the size the chart has now, so it is worked out again whenever the chart is resized. The chart's own
    // observer (in Chart.tsx) was registered first, so by the time this one runs the layout is the new one.
    const measure = () => {
      const chart = echarts.getInstanceByDom(el);
      if (!chart) return;
      const small = tooLittleRoom(chart, drawn);
      setUnlabelled((before) => (before.length === small.length && before.every((id, i) => id === small[i]) ? before : small));
    };
    measure();
    const watcher = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watcher?.observe(el);
    return () => watcher?.disconnect();
  }, [option, drawn]);

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
    <div className="chart-frame" ref={frame}>
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
      {drawn.length > 0 && <Chart option={option} label={`${label}: ${focus.name}`} onClick={clicked} />}
      {nodes.length > 0 && <ul className="chart-list" aria-label={`${label}, as a list`}>
        {nodes.map((node) => {
          const slot = slotOf(node, trail);
          return (
            <li key={node.id}>
              <button className="chart-item" onClick={() => open(node)}>
                <span className={`chart-swatch${slot ? ` chart-slot-${slot}` : ""}`} aria-hidden="true" />
                <span className="chart-item-name">{node.name}{node.children?.length ? <span className="m"> ▸</span> : null}{isDrawn(node) ? null : <span className="m"> · not in the chart</span>}
                  {node.note && <span className="chart-item-note">{node.note}</span>}</span>
                <span className="num">{format(node)}</span>
              </button>
            </li>
          );
        })}
      </ul>}
    </div>
  );
}

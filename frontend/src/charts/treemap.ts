import type { EChartsCoreOption } from "./echarts";
import { type ChartTheme, onColor, SLOTS } from "./theme";
import { tooltipOption } from "./tooltip";

/** A node of a hierarchy to draw as a treemap. `size` is the area; `slot` (a whole number from 1: past the palette's size it repeats, see
 *  `slotFor`) is the colour, given to the entity and never to its rank, so a filter that removes a type does not repaint the others.
 *  A node without one takes its parent's. A node with children can be drilled into. */
export type TreeNode = { id: string; name: string; size: number; slot?: number; note?: string; children?: TreeNode[] };

/** Whether a block can be drawn. A block cannot be negative or empty, so a node with no area is only in the list. */
export const isDrawn = (node: TreeNode) => node.size > 0;

/** The nodes from the root down the ids of `path`, stopping at the first id that is not there (a filter may have removed it). */
export function trailOf(root: TreeNode, path: string[]): TreeNode[] {
  const trail = [root];
  for (const id of path) {
    const next = trail[trail.length - 1].children?.find((n) => n.id === id);
    if (!next) break;
    trail.push(next);
  }
  return trail;
}

/** The slot a block takes: its own, else the nearest parent's, else none (drawn in the muted colour). The palette has SLOTS colours and a
 *  report may have more entities than that: slot SLOTS + 1 is slot 1 again. The size of the palette never decides what a report shows
 *  (whether a report has an "Others" group is its owner's decision), so a colour may repeat, and what tells blocks apart is the label,
 *  the list and the tooltip. */
export function slotOf(node: TreeNode, trail: TreeNode[]): number | undefined {
  const own = node.slot ?? [...trail].reverse().find((n) => n.slot !== undefined)?.slot;
  return own !== undefined && Number.isInteger(own) && own >= 1 ? ((own - 1) % SLOTS) + 1 : undefined;
}

/** The ECharts option for the blocks of `nodes` (the children of the node drilled into, whose path is `trail`). Drilling is the caller's
 *  state, not ECharts': the blocks are redrawn from the chosen node's children, so the breadcrumb and the list are real controls and
 *  the same data, and the chart is only a picture of them. */
export function treemapOption(nodes: TreeNode[], trail: TreeNode[], theme: ChartTheme, format: (node: TreeNode) => string, unlabelled: ReadonlySet<string> = new Set()): EChartsCoreOption {
  const data = nodes.filter(isDrawn).map((node) => {
    const slot = slotOf(node, trail);
    const fill = slot ? theme.series[slot - 1] : theme.muted;
    return { id: node.id, name: node.name, value: node.size, text: format(node), note: node.note, slot, itemStyle: { color: fill },
             label: { color: onColor(fill), show: !unlabelled.has(node.id) } };
  });
  return {
    tooltip: tooltipOption((params) => {
      const item = params.data as { text?: string; slot?: number; note?: string } | undefined;
      return item?.text === undefined ? null : { title: params.name ?? "", slot: item.slot, rows: [{ label: "Value", value: item.text }], note: item.note };
    }),
    series: [{
      type: "treemap", data, left: 0, top: 0, right: 0, bottom: 0, roam: false, nodeClick: false, breadcrumb: { show: false },
      itemStyle: { borderColor: theme.surface, borderWidth: 2, gapWidth: 0 },
      label: { show: true, position: "insideTopLeft", fontSize: 13, lineHeight: 20, padding: [4, 8, 4, 8], formatter: (p: { name: string; data: { text: string } }) => `${p.name}\n${p.data.text}` },
    }],
  };
}

/** A block is given a label only if it has room for it: at least this wide and this high, in pixels. */
const LABEL_ROOM = { width: 78, height: 50 };

/** The ids of the blocks of a drawn treemap that are too small to hold their label, from the layout ECharts worked out. The list and the
 *  tooltip still name them. `drawn` is the nodes in the order they were given to the chart (a treemap's first layout item is its root). */
export function tooLittleRoom(chart: object, drawn: TreeNode[]): string[] {
  // `getModel` is private in ECharts' types and is the way to the layout it worked out.
  const data = ((chart as { getModel: () => unknown }).getModel() as { getSeriesByIndex: (i: number) => { getData: () => { getItemLayout: (i: number) => { width: number; height: number } | undefined } } })
    .getSeriesByIndex(0).getData();
  return drawn.filter((_, i) => {
    const box = data.getItemLayout(i + 1);
    return box !== undefined && (box.width < LABEL_ROOM.width || box.height < LABEL_ROOM.height);
  }).map((node) => node.id);
}

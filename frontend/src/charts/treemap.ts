import type { EChartsCoreOption } from "./echarts";
import { type ChartTheme, onColor, SLOTS } from "./theme";
import { tooltipOption } from "./tooltip";

/** A node of a hierarchy to draw as a treemap. `size` is the area; `slot` (1 to 8) is the colour, given to the entity and never to its
 *  rank, so a filter that removes a type does not repaint the others. A node without one takes its parent's. A node with children can be
 *  drilled into. */
export type TreeNode = { id: string; name: string; size: number; slot?: number; children?: TreeNode[] };

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

/** The slot a block takes: its own, else the nearest parent's, else none (drawn in the muted colour). */
export function slotOf(node: TreeNode, trail: TreeNode[]): number | undefined {
  const own = node.slot ?? [...trail].reverse().find((n) => n.slot !== undefined)?.slot;
  return own !== undefined && own >= 1 && own <= SLOTS ? own : undefined;
}

/** The ECharts option for the blocks of `nodes` (the children of the node drilled into, whose path is `trail`). Drilling is the caller's
 *  state, not ECharts': the blocks are redrawn from the chosen node's children, so the breadcrumb and the list are real controls and
 *  the same data, and the chart is only a picture of them. */
export function treemapOption(nodes: TreeNode[], trail: TreeNode[], theme: ChartTheme, format: (node: TreeNode) => string): EChartsCoreOption {
  const data = nodes.map((node) => {
    const slot = slotOf(node, trail);
    const fill = slot ? theme.series[slot - 1] : theme.muted;
    return { id: node.id, name: node.name, value: node.size, text: format(node), slot, itemStyle: { color: fill }, label: { color: onColor(fill) } };
  });
  return {
    tooltip: tooltipOption((params) => {
      const item = params.data as { text?: string; slot?: number } | undefined;
      return item?.text === undefined ? null : { title: params.name ?? "", rows: [{ label: "Value", value: item.text, slot: item.slot }] };
    }),
    series: [{
      type: "treemap", data, left: 0, top: 0, right: 0, bottom: 0, roam: false, nodeClick: false, breadcrumb: { show: false },
      itemStyle: { borderColor: theme.surface, borderWidth: 2, gapWidth: 0 },
      label: { show: true, position: "insideTopLeft", fontSize: 13, formatter: (p: { name: string; data: { text: string } }) => `${p.name}\n${p.data.text}` },
    }],
  };
}

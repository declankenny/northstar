/** What a page can draw of each kind of section. The server lists the same views in `northstar/reports/sections.py` (VIEWS and
 *  NEEDS_SIZE), and a test fails when the two lists differ. A view is only a name: the contract carries no chart configuration. */
export const VIEWS = {
  summary: ["tiles"],
  series: ["line"],
  hierarchy: ["treemap", "waterfall", "table"],
  rows: ["table"],
} as const;

/** The views that draw by size, so a section they draw must be sized. */
export const VIEWS_THAT_NEED_SIZE = ["treemap"] as const;

export type SectionKind = keyof typeof VIEWS;
export type View = (typeof VIEWS)[SectionKind][number];

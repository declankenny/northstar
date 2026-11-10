import type { ListColumn, ListRow } from "./api";
import { formatDate } from "./dates";
import { formatCell } from "./listFormat";
import { formatInteger } from "./locale";

/** What a grouped list needs apart from how it is drawn: the runs of rows that are one group, what a group is called, which groups are
 *  collapsed, and what the group header says. The server orders the rows by group, so a group is a run of neighbouring rows. */

/** A run of neighbouring rows of one group on this page. `total` is the group's size across all pages and `here` how many of its rows
 *  are on this page; `continued` says the page opens on a group that began on the page before. */
export type Section = { id: string; value: unknown; total: number; here: number; continued: boolean; rows: ListRow[] };

/** The group a row is in, as the server said it: a value, or null for no value. */
export const groupOf = (row: ListRow): unknown => row._group ?? null;

/** Text that names a group, which is also its key in what is collapsed. A group with no value is its own group, never the text "null". */
export const groupId = (value: unknown): string => (value === null || value === undefined ? "none" : `value:${String(value)}`);

/** The page's rows cut into sections, one for each run of rows of the same group. A group is never cut in the middle of a page. */
export function sections(rows: ListRow[]): Section[] {
  const found: Section[] = [];
  rows.forEach((row, i) => {
    const value = groupOf(row);
    const id = groupId(value);
    const last = found[found.length - 1];
    if (last && last.id === id) {
      last.rows.push(row);
      last.here += 1;
      return;
    }
    found.push({ id, value, total: Number(row._group_count ?? 1), here: 1, continued: i === 0 && Number(row._group_before ?? 0) > 0, rows: [row] });
  });
  return found;
}

/** Which groups are collapsed. Either every group is open except these, or every group is collapsed except these, so that Expand all
 *  and Collapse all reach the groups on other pages too, which this page has not seen. */
export type Collapsing = { all: boolean; except: ReadonlySet<string> };

export const OPEN: Collapsing = { all: false, except: new Set() };
export const COLLAPSED: Collapsing = { all: true, except: new Set() };

export const isCollapsed = (state: Collapsing, id: string): boolean => (state.all ? !state.except.has(id) : state.except.has(id));

/** The state after one group's header is pressed. */
export function toggled(state: Collapsing, id: string): Collapsing {
  const except = new Set(state.except);
  if (except.has(id)) except.delete(id);
  else except.add(id);
  return { all: state.all, except };
}

/** What a group is called, written as its column writes a value, or null for a group with no value. `kind` and `scale` are the column's.
 *  A timestamp is grouped by its UTC date, so it is written as a date. */
export function groupLabel(kind: ListColumn["kind"] | undefined, scale: number | null, value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (kind === "yes_no") return value === 1 || value === true || value === "1" ? "Yes" : "No";
  if (kind === "timestamp" || kind === "date") return formatDate(String(value).slice(0, 10));
  if (kind === undefined) return String(value);
  return formatCell({ key: "", label: "", path_label: "", linked: false, groupable: true, kind, scale }, value) ?? String(value);
}

/** What a group header says beside the name: "3 rows", or "9 rows (4 on this page)" when the group goes on to another page. */
export function groupSummary(section: Section): string {
  const rows = `${formatInteger(section.total)} row${section.total === 1 ? "" : "s"}`;
  return section.here < section.total ? `${rows} (${formatInteger(section.here)} on this page)` : rows;
}

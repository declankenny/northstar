import { type ComponentType, useMemo } from "react";
import { TreemapDrill } from "../charts/TreemapDrill";
import type { TreeNode } from "../charts/treemap";
import { formatDate } from "../dates";
import { listAddress, parseListView, withFilters } from "../listState";
import { formatInteger } from "../locale";
import { type Currency, formatCents } from "../money";
import { navigate, Link } from "../router";
import { accountPath, balancePath } from "../routes";
import type {
  HierarchyData, HierarchyNode, ReportLink, ReportSectionDeclaration, RowCell, RowsData, SectionData, SummaryData, SummaryItem,
} from "./types";
import type { View } from "./views";

/** What a view is handed: the section as the report declared it, its data as the server checked it, and the currency every amount is in. */
export type ViewProps = { section: ReportSectionDeclaration; data: SectionData; currency: Currency };

/** Where a drill target goes, or null when this page does not know the place (a list it has no address for). */
export function linkHref(link: ReportLink | undefined): string | null {
  if (!link) return null;
  if (link.to === "account") return accountPath(link.id);
  if (link.to === "balance") return balancePath(link.id);
  return /^[a-z][a-z0-9_]*$/.test(link.list) ? listAddress(`/${link.list}`, withFilters(parseListView(""), link.filters)) : null;
}

/** An amount in the report's currency. */
const money = (minor: number, currency: Currency) => formatCents(minor, currency);

/** An amount in another currency. The contract names the currency and carries its amount in that currency's minor units, but not how
 *  many decimal places it has, so the page cannot write it as an amount without guessing: it says what it was given.
 *  TODO: when a report needs these, the contract carries the currency's decimal places. */
const foreign = (minor: number, code: string) => `${code} ${formatInteger(minor)} (minor units)`;

function summaryValue(item: SummaryItem, currency: Currency): string {
  switch (item.kind) {
    case "money": return item.currency && item.currency !== currency.code ? foreign(item.value, item.currency) : money(item.value, currency);
    case "count": return formatInteger(item.value);
    case "date": return formatDate(item.value);
    default: return item.value;
  }
}

/** Headline figures: one tile each. A report's first summary sits at the top right of the page header, outside the grid. */
export function TilesView({ data, currency }: ViewProps) {
  const { items } = data as SummaryData;
  return (
    <div className="rp-tiles">
      {items.map((item) => (
        <div className="tile" key={item.key}>
          <div className="label">{item.label}</div>
          <div className="val num">{summaryValue(item, currency)}</div>
          {item.note && <div className="sub">{item.note}</div>}
        </div>
      ))}
    </div>
  );
}

function cellText(cell: RowCell, kind: RowsData["columns"][number]["kind"], currency: Currency): string {
  if (cell === null) return "—";
  if (typeof cell === "object") return foreign(cell.minor, cell.currency);
  if (kind === "money" && typeof cell === "number") return money(cell, currency);
  if (kind === "count" && typeof cell === "number") return formatInteger(cell);
  if (kind === "date") return formatDate(String(cell));
  return String(cell);
}

/** Every node of a hierarchy, parents before their children, with how deep each is. */
function flatten(nodes: HierarchyNode[], depth = 0): { node: HierarchyNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flatten(node.children ?? [], depth + 1)]);
}

/** A hierarchy as a table: its nodes in order, each child indented under its parent, with the value a person reads (signed, and
 *  a parent's the sum of its children's). A node with a drill target makes its name a link. */
function HierarchyTable({ section, data, currency }: { section: ReportSectionDeclaration; data: HierarchyData; currency: Currency }) {
  const lines = flatten(data.nodes);
  return (
    <>
      <h2>{section.title}</h2>
      {lines.length === 0 ? <p className="empty">Nothing to list.</p> : (
        <div className="gcard">
          <table className="num lf-table">
            <thead><tr><th>Name</th><th className="r">Value</th></tr></thead>
            <tbody>
              {lines.map(({ node, depth }, i) => {
                const href = linkHref(node.link);
                return (
                  <tr key={i} className={node.children?.length ? "rp-parent" : undefined}>
                    <td><span className={depth > 0 ? `rp-depth-${Math.min(depth, 8)}` : undefined}>{href ? <Link to={href}>{node.label}</Link> : node.label}</span></td>
                    <td className="r">{money(node.value, currency)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** Rows as a table (or a hierarchy as one, which has its own payload). A row with a drill target makes its first cell a link. */
export function TableView({ section, data, currency }: ViewProps) {
  if ("nodes" in data) return <HierarchyTable section={section} data={data} currency={currency} />;
  const { columns, rows } = data as RowsData;
  const numeric = (kind: string) => kind === "money" || kind === "native_money" || kind === "count";
  return (
    <>
      <h2>{section.title}</h2>
      {rows.length === 0 ? <p className="empty">Nothing to list.</p> : (
        <div className="gcard">
          <table className="num lf-table">
            <thead><tr>{columns.map((c) => <th key={c.key} className={numeric(c.kind) ? "r" : ""}>{c.label}</th>)}</tr></thead>
            <tbody>
              {rows.map((row) => {
                const href = linkHref(row.link);
                return (
                  <tr key={row.id}>
                    {columns.map((c, i) => {
                      const text = cellText(row.cells[c.key] ?? null, c.kind, currency);
                      return <td key={c.key} className={numeric(c.kind) ? "r" : ""}>{i === 0 && href ? <Link to={href}>{text}</Link> : text}</td>;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** A hierarchy as a node of the chart's own kind. The id is the path, so it is unique across the tree, and the value (signed, and what
 *  a person reads) is kept beside the size (what the area is). */
function toTree(nodes: HierarchyNode[], prefix: string, values: Map<string, number>, links: Map<string, ReportLink | undefined>): TreeNode[] {
  return nodes.map((node) => {
    const id = `${prefix}/${node.id}`;
    values.set(id, node.value);
    links.set(id, node.link);
    const children = node.children?.length ? toTree(node.children, id, values, links) : undefined;
    return { id, name: node.label, size: node.size ?? 0, children };
  });
}

/** A hierarchy drawn as a treemap you can drill into, with the same nodes as a list of buttons. The nodes' colours and the rest of what
 *  a particular report needs of it are the report's own work; this is the shared view. */
export function TreemapView({ section, data, currency }: ViewProps) {
  const { nodes } = data as HierarchyData;
  const { root, values, links } = useMemo(() => {
    const values = new Map<string, number>(), links = new Map<string, ReportLink | undefined>();
    const children = toTree(nodes, section.key, values, links);
    return { root: { id: section.key, name: section.title, size: children.reduce((total, n) => total + n.size, 0), children } as TreeNode, values, links };
  }, [nodes, section]);
  const format = useMemo(() => (node: TreeNode) => money(values.get(node.id) ?? node.size, currency), [values, currency]);
  return (
    <TreemapDrill root={root} format={format} label={section.title}
      onLeaf={(node) => { const href = linkHref(links.get(node.id)); if (href) navigate(href); }} />
  );
}

/** A view the page has no drawing for yet. It says so, so a report that names it shows an honest message and not nothing. */
export function UnavailableView({ section }: ViewProps) {
  return (
    <>
      <h2>{section.title}</h2>
      <p className="empty">This kind of chart is not available yet.</p>
    </>
  );
}

/** One component for every view the server can declare. The type makes the compiler refuse a view without one, and a test checks the
 *  server's own list. `line` has no chart yet (each chart type is added, with its probe, when the first report uses it). */
export const VIEW_COMPONENTS: Record<View, ComponentType<ViewProps>> = {
  tiles: TilesView,
  line: UnavailableView,
  treemap: TreemapView,
  table: TableView,
};

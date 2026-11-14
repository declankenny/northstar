import { type ComponentType, useMemo, useState } from "react";
import { slotFor } from "../charts/colour";
import { TreemapDrill } from "../charts/TreemapDrill";
import type { TreeNode } from "../charts/treemap";
import { WaterfallChart } from "../charts/WaterfallChart";
import type { Words } from "../charts/waterfall";
import { formatDate } from "../dates";
import { listAddress, parseListView, withFilters } from "../listState";
import { formatInteger } from "../locale";
import { type Currency, formatCents, formatCompact, formatWhole } from "../money";
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
          <div className="val num">{item.kind === "money" && item.signed && !item.currency ? <Change value={item.value} currency={currency} /> : summaryValue(item, currency)}</div>
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

/** The nodes of a hierarchy that are showing, parents before their children, with how deep each is: a parent's children are showing only while it
 *  is open. */
function visible(nodes: HierarchyNode[], isOpen: (node: HierarchyNode) => boolean, depth = 0): { node: HierarchyNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...(node.children?.length && isOpen(node) ? visible(node.children, isOpen, depth + 1) : [])]);
}

/** A change, with its sign and the colour of its direction (a sign too, so the colour is never all there is). */
function Change({ value, currency }: { value: number; currency: Currency }) {
  return <span className="delta"><span className={value > 0 ? "p" : value < 0 ? "n" : "m"}>{value > 0 ? "+" : ""}{money(value, currency)}</span></span>;
}

/** A hierarchy as a table: its nodes in order, each child indented under its parent, with the value a person reads (signed, and a parent's the sum
 *  of its children's). A parent opens and closes with a button, expanded or collapsed to begin with as the section says, and keeps the way a
 *  person left it when the report is worked out again. A node with a drill target makes its name a link. A hierarchy that compares two dates
 *  (its nodes have `opening` and `closing`) shows both, the change, and the note, which says which balances they rest on. */
function HierarchyTable({ section, data, currency }: { section: ReportSectionDeclaration; data: HierarchyData; currency: Currency }) {
  const [flipped, setFlipped] = useState<Set<string>>(new Set());              // the parents whose state is not the section's
  const isOpen = (node: HierarchyNode) => section.expanded !== flipped.has(node.id);
  const flip = (id: string) => setFlipped((before) => { const next = new Set(before); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const compared = data.nodes.some((n) => n.opening !== undefined);
  const lines = visible(data.nodes, isOpen);
  return (
    <>
      <h2>{section.title}</h2>
      {data.nodes.length === 0 ? <p className="empty">Nothing to list.</p> : (
        <div className="gcard">
          <table className="num lf-table">
            <thead><tr>
              <th>{compared ? "Type and account" : "Name"}</th>
              {compared ? <><th className="r">Opening</th><th className="r">Closing</th><th className="r">Change</th><th>Balances used</th></> : <th className="r">Value</th>}
            </tr></thead>
            <tbody>
              {lines.map(({ node, depth }) => {
                const href = linkHref(node.link);
                const parent = !!node.children?.length;
                return (
                  <tr key={node.id} className={parent ? "rp-parent" : undefined}>
                    <td><span className={depth > 0 ? `rp-depth-${Math.min(depth, 8)}` : undefined}>
                      {parent
                        ? <button className="link rp-expander" aria-expanded={isOpen(node)} onClick={() => flip(node.id)}><span aria-hidden="true">{isOpen(node) ? "▾" : "▸"}</span> {node.label}</button>
                        : href ? <Link to={href}>{node.label}</Link> : node.label}
                    </span></td>
                    {compared ? (
                      <>
                        <td className="r">{node.opening === undefined ? "" : money(node.opening, currency)}</td>
                        <td className="r">{node.closing === undefined ? "" : money(node.closing, currency)}</td>
                        <td className="r"><Change value={node.value} currency={currency} /></td>
                        <td className="m">{node.note}</td>
                      </>
                    ) : <td className="r">{money(node.value, currency)}</td>}
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
    // A colour is named by the entity it comes from, and the page turns that into a slot from the id alone, so it is the same everywhere.
    const slot = node.colour ? slotFor(node.colour.kind, node.colour.id) : undefined;
    return { id, name: node.label, size: node.size ?? 0, slot, note: node.note, children };
  });
}

/** A hierarchy drawn as a treemap you can drill into, with the same nodes as a list of buttons. A node's colour comes from the entity the report
 *  names (`colour`), else its parent's; its note is shown in its tooltip; a node with no area is only in the list. */
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

/** How a waterfall writes an amount: exact (a tooltip), with its sign (a change), and short (a label with little room, or the scale). */
function wordsFor(currency: Currency): Words {
  const sign = (value: number, text: (n: number) => string) => (value > 0 ? "+" : "") + text(value);
  return {
    amount: (value) => money(value, currency), change: (value) => sign(value, (n) => money(n, currency)),
    short: (value) => formatCompact(value, currency), shortChange: (value) => sign(value, (n) => formatCompact(n, currency)),
    whole: (value) => formatWhole(value, currency),
  };
}

/** A hierarchy that compares two dates, drawn as a waterfall: the opening balance, a step for each top-level node (its change, from the
 *  running total) and the closing balance. The report gives the whole at each end (accounts that did not change are in it and in no node),
 *  so the chart does no arithmetic of its own beyond adding the steps' changes to place the bars. */
export function WaterfallView({ section, data, currency }: ViewProps) {
  const { nodes, opening, closing } = data as HierarchyData;
  const words = useMemo(() => wordsFor(currency), [currency]);
  const whole = useMemo(() => (opening === undefined || closing === undefined ? undefined : { opening, closing }), [opening, closing]);
  const steps = useMemo(() => nodes.map((n) => ({ id: n.id, name: n.label, value: n.value, opening: n.opening ?? 0, closing: n.closing ?? 0, note: n.note })), [nodes]);
  return (
    <>
      <h2>{section.title}</h2>
      {steps.length === 0 ? <p className="empty">Nothing to chart.</p> : <WaterfallChart nodes={steps} whole={whole} words={words} label={section.title} />}
    </>
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
  waterfall: WaterfallView,
  table: TableView,
};

// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { giveBoxesASize } from "../charts/chartTesting";
import { formatDate } from "../dates";
import { ExpansionProvider } from "./expansion";
import { linkHref, TableView, TilesView, TreemapView, UnavailableView, VIEW_COMPONENTS, type ViewProps, WaterfallView } from "./viewComponents";
import type { ReportSectionDeclaration, RowsData, SummaryData, HierarchyData } from "./types";
import { VIEWS } from "./views";

let restore: () => void;
beforeEach(() => {
  restore = giveBoxesASize(640, 360);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  window.history.replaceState(null, "", "/reports/probe");
});
afterEach(() => { cleanup(); restore(); vi.restoreAllMocks(); });

const USD = { code: "USD", name: "USD", minor_units: 2 };
const section = (kind: ReportSectionDeclaration["kind"], view: ReportSectionDeclaration["view"], over: Partial<ReportSectionDeclaration> = {}): ReportSectionDeclaration =>
  ({ key: "s", kind, view, title: "Section", sized: false, columns: 12, expanded: true, ...over });
const props = (kindView: [ReportSectionDeclaration["kind"], ReportSectionDeclaration["view"]], data: ViewProps["data"], over: Partial<ReportSectionDeclaration> = {}): ViewProps =>
  ({ section: section(kindView[0], kindView[1], over), data, currency: USD });

describe("the views", () => {
  it("have a component for every view the server can declare, each kind and each name", () => {
    const declared = Object.values(VIEWS).flat();
    expect(declared.length).toBeGreaterThan(0);
    for (const view of declared) expect(typeof VIEW_COMPONENTS[view], view).toBe("function");
    expect(Object.keys(VIEW_COMPONENTS).sort()).toEqual([...new Set(declared)].sort());          // and none that the server does not declare
  });

  it("say so for a view with no drawing yet, instead of showing nothing", () => {
    render(<UnavailableView {...props(["series", "line"], { series: [] }, { title: "Trend" })} />);
    expect(screen.getByRole("heading", { name: "Trend" })).toBeTruthy();
    expect(screen.getByText("This kind of chart is not available yet.")).toBeTruthy();
    expect(VIEW_COMPONENTS.line).toBe(UnavailableView);
  });
});

describe("where a drill target goes", () => {
  it("is the account's page, the balance's page, or a list with the filters", () => {
    expect(linkHref({ to: "account", id: 12 })).toBe("/accounts/12");
    expect(linkHref({ to: "balance", id: 7 })).toBe("/balances/7");
    const href = linkHref({ to: "list", list: "balances", filters: [{ field: "account", operator: "is", value: 3 }] })!;
    expect(href.startsWith("/balances?")).toBe(true);
    expect(decodeURIComponent(href)).toContain('"field":"account"');
  });

  it("is nowhere for no target, and for a list whose name is not a plain name", () => {
    expect(linkHref(undefined)).toBeNull();
    expect(linkHref({ to: "list", list: "../x", filters: [] })).toBeNull();
    expect(linkHref({ to: "list", list: "Bad Name", filters: [] })).toBeNull();
  });
});

describe("headline figures", () => {
  const items: SummaryData = { items: [
    { key: "net", label: "Net worth", kind: "money", value: 123_456 }, { key: "n", label: "Accounts", kind: "count", value: 1234 },
    { key: "d", label: "As at", kind: "date", value: "2026-11-11" }, { key: "t", label: "Basis", kind: "text", value: "Latest balance", note: "As entered" },
    { key: "eur", label: "In euros", kind: "money", value: 5_000, currency: "EUR" }, { key: "usd", label: "In dollars", kind: "money", value: 700, currency: "USD" },
  ] };

  it("are a tile each, a money amount in the report's currency, a count, a date, a text, and a note beside the figure", () => {
    const { container } = render(<TilesView {...props(["summary", "tiles"], items)} />);
    const tile = (label: string) => within(screen.getByText(label).closest(".tile") as HTMLElement);
    expect(tile("Net worth").getByText("$1,234.56")).toBeTruthy();
    expect(tile("Accounts").getByText("1,234")).toBeTruthy();
    expect(tile("As at").getByText(formatDate("2026-11-11"))).toBeTruthy();
    expect(tile("Basis").getByText("Latest balance")).toBeTruthy();
    expect(tile("Basis").getByText("As entered")).toBeTruthy();
    expect(tile("In dollars").getByText("$7.00")).toBeTruthy();
    expect(container.querySelectorAll(".tile")).toHaveLength(6);
  });

  it("never guess the decimal places of an amount in another currency: it says what it was given", () => {
    render(<TilesView {...props(["summary", "tiles"], items)} />);
    expect(within(screen.getByText("In euros").closest(".tile") as HTMLElement).getByText("EUR 5,000 (minor units)")).toBeTruthy();
  });
});

describe("a signed headline figure", () => {
  const change = (value: number, over: object = {}): SummaryData => ({ items: [{ key: "change", label: "Change", kind: "money", value, signed: true, ...over }] });
  const figure = (container: HTMLElement) => container.querySelector(".tile .val .delta span")!;

  it("is a change: shown with its sign and coloured by its direction, in the tile's own size", () => {
    const up = render(<TilesView {...props(["summary", "tiles"], change(300_000))} />);
    expect(figure(up.container).textContent).toBe("+$3,000.00");
    expect(figure(up.container).className).toBe("p");
    cleanup();
    const down = render(<TilesView {...props(["summary", "tiles"], change(-5_000))} />);
    expect(figure(down.container).textContent).toBe("-$50.00");
    expect(figure(down.container).className).toBe("n");
    cleanup();
    expect(figure(render(<TilesView {...props(["summary", "tiles"], change(0))} />).container).className).toBe("m");
  });

  it("is not coloured when the report does not say it is a change, or when it is in another currency", () => {
    const plain = render(<TilesView {...props(["summary", "tiles"], change(300_000, { signed: undefined }))} />);
    expect(plain.container.querySelector(".delta")).toBeNull();
    expect(plain.container.querySelector(".val")!.textContent).toBe("$3,000.00");
    cleanup();
    const foreignFigure = render(<TilesView {...props(["summary", "tiles"], change(5_000, { currency: "EUR" }))} />);
    expect(foreignFigure.container.querySelector(".delta")).toBeNull();
  });
});

describe("a hierarchy drawn as a waterfall", () => {
  const data: HierarchyData = { nodes: [
    { id: "type_1", label: "Brokerage", value: 600_000, opening: 1_000_000, closing: 1_600_000, note: "2 accounts", children: [
      { id: "account_1", label: "Index fund", value: 700_000, opening: 1_000_000, closing: 1_700_000 }, { id: "account_2", label: "Stocks", value: -100_000, opening: 0, closing: -100_000 }] },
    { id: "type_2", label: "Mortgage", value: -200_000, opening: 500_000, closing: 300_000, note: "1 account" },
  ] };
  const colours = () => {
    document.documentElement.style.setProperty("--pos", "#118811");
    document.documentElement.style.setProperty("--neg", "#cc2222");
    document.documentElement.style.setProperty("--accent", "#2233cc");
  };
  const waterfall = (d: HierarchyData, over: Partial<ReportSectionDeclaration> = {}) =>
    render(<WaterfallView {...props(["hierarchy", "waterfall"], d, { title: "How it changed", expanded: false, ...over })} />);

  it("draws the opening balance, a step for each type and the closing balance, with its title", () => {
    const { container } = waterfall(data);
    expect(screen.getByRole("heading", { name: "How it changed" })).toBeTruthy();
    const text = container.querySelector(".bridge-scroll")!.textContent!;
    for (const expected of ["Opening balance", "Brokerage", "Mortgage", "Closing balance", "$15,000", "$19,000", "+$6K", "-$2K"]) expect(text).toContain(expected);
  });

  it("describes the figures for a screen reader, in the report's currency, and does not draw an account of a type as a step of its own", () => {
    const { container } = waterfall(data);
    const label = container.querySelector(".bridge-scroll .chart-canvas")!.getAttribute("aria-label")!;
    expect(label).toBe("How it changed: Opening balance $15,000.00, Brokerage +$6,000.00, Mortgage -$2,000.00, Closing balance $19,000.00");
    expect(label).not.toContain("Index fund");
  });

  it("starts and ends at the whole the report gives, since an account that did not change is in the whole and in no type", () => {
    const { container } = waterfall({ ...data, opening: 2_500_000, closing: 2_900_000 });
    const label = container.querySelector(".bridge-scroll .chart-canvas")!.getAttribute("aria-label")!;
    expect(label).toBe("How it changed: Opening balance $25,000.00, Brokerage +$6,000.00, Mortgage -$2,000.00, Closing balance $29,000.00");
  });

  const tree: HierarchyData = { nodes: [
    { id: "type_1", label: "Brokerage", value: 600_000, opening: 1_000_000, closing: 1_600_000, note: "2 accounts", children: [
      { id: "account_1", label: "Index fund", value: 700_000, opening: 1_000_000, closing: 1_700_000, link: { to: "account", id: 11 } },
      { id: "account_2", label: "Stocks", value: -100_000, opening: 0, closing: -100_000, link: { to: "account", id: 12 } }] },
    { id: "type_2", label: "Mortgage", value: -200_000, opening: 500_000, closing: 300_000, note: "1 account", children: [
      { id: "account_3", label: "Home loan", value: -200_000, opening: 500_000, closing: 300_000, link: { to: "account", id: 13 } }] },
  ] };
  const both = () => render(
    <ExpansionProvider>
      <WaterfallView {...props(["hierarchy", "waterfall"], tree, { key: "bridge", title: "How it changed", expanded: false })} />
      <TableView {...props(["hierarchy", "table"], tree, { key: "changes", title: "Detail", expanded: false })} />
    </ExpansionProvider>);
  const chartText = (container: HTMLElement) => container.querySelector(".bridge-scroll")!.textContent!;
  const rowsOf = (container: HTMLElement) => [...container.querySelectorAll("tbody tr")].map((r) => r.textContent!.trim());

  it("starts with every type closed, in the chart and in the table, when its section starts collapsed", () => {
    const { container } = both();
    expect(chartText(container)).not.toContain("Index fund");
    expect(chartText(container)).toContain("▸ Brokerage");
    expect(rowsOf(container)).toHaveLength(2);
  });

  it("opens a type in the chart when it is opened in the table, and in the table when it is opened in the chart, so the two agree", () => {
    const { container } = both();
    fireEvent.click(screen.getByRole("button", { name: /Brokerage/ }));                        // the table's button
    expect(chartText(container)).toContain("Index fund");
    expect(chartText(container)).toContain("▾ Brokerage");
    expect(rowsOf(container)).toHaveLength(4);
    expect(rowsOf(container).some((r) => r.startsWith("Index fund"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Brokerage/ }));                        // closed again
    expect(chartText(container)).not.toContain("Index fund");
    expect(rowsOf(container)).toHaveLength(2);
  });

  it("has Expand all and Collapse all above the chart, which open and close every type in the chart and in the table", () => {
    const { container } = both();
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    for (const name of ["Index fund", "Stocks", "Home loan"]) expect(chartText(container)).toContain(name);
    expect(rowsOf(container)).toHaveLength(5);
    expect(screen.getAllByRole("button", { name: /Brokerage|Mortgage/ }).every((b) => b.getAttribute("aria-expanded") === "true")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(chartText(container)).not.toContain("Index fund");
    expect(rowsOf(container)).toHaveLength(2);
  });

  it("keeps the totals and the net change the same whichever types are open", () => {
    const { container } = both();
    const label = () => container.querySelector(".bridge-scroll .chart-canvas")!.getAttribute("aria-label")!;
    const ends = () => [/Opening balance \$[\d,.]+/.exec(label())![0], /Closing balance \$[\d,.]+/.exec(label())![0]];
    const before = ends();
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(ends()).toEqual(before);
  });

  it("offers Expand all and Collapse all only when there is something to open", () => {
    waterfall({ nodes: [{ id: "x", label: "X", value: 5, opening: 1, closing: 6 }] });
    expect(screen.queryByRole("button", { name: "Expand all" })).toBeNull();
  });

  it("starts open, and Expand all and Collapse all still mean open and closed, when its section starts expanded", () => {
    const { container } = waterfall(tree, { expanded: true });
    expect(chartText(container)).toContain("Index fund");
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(chartText(container)).not.toContain("Index fund");
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(chartText(container)).toContain("Index fund");
  });

  it("works without a report around it: a view on its own keeps its own state", () => {
    const { container } = waterfall(tree);
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(chartText(container)).toContain("Home loan");
  });

  it("goes to an account's page when its bar is clicked, and opens a closed type instead of leaving the page", () => {
    colours();
    const { container } = waterfall(tree);
    const svg = () => container.querySelector(".bridge-scroll .chart-canvas svg")!;
    const press = (x: number, y: number) => { for (const type of ["mouseMove", "mouseDown", "mouseUp", "click"] as const) fireEvent[type](svg(), { clientX: x, clientY: y }); };
    const middleOf = (fill: string) => {
      const path = [...svg().querySelectorAll("path")].find((p) => p.getAttribute("fill")?.toLowerCase() === fill)!;
      const points = [...(path.getAttribute("d") ?? "").matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
      const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
      return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
    };
    press(...(middleOf("#118811") as [number, number]));                                    // Brokerage, closed: it opens
    expect(window.location.pathname).toBe("/reports/probe");
    expect(chartText(container)).toContain("Index fund");
    press(...(middleOf("#118811") as [number, number]));                                    // Index fund, the first green bar: its page
    expect(window.location.pathname).toBe("/accounts/11");
  });

  it("says there is nothing to chart when nothing changed, instead of an empty chart", () => {
    const { container } = waterfall({ nodes: [] });
    expect(screen.getByText("Nothing to chart.")).toBeTruthy();
    expect(container.querySelector(".chart-canvas")).toBeNull();
  });
});

describe("a table", () => {
  const rows: RowsData = {
    columns: [{ key: "name", label: "Account", kind: "text" }, { key: "value", label: "Value", kind: "money" }, { key: "n", label: "Count", kind: "count" },
      { key: "on", label: "Date", kind: "date" }, { key: "native", label: "Balance", kind: "native_money" }],
    rows: [
      { id: "r1", cells: { name: "Alpha", value: 250_000, n: 3, on: "2026-10-31", native: { minor: 3_720_00, currency: "EUR" } }, link: { to: "account", id: 5 } },
      { id: "r2", cells: { name: "Beta", value: -12_500, n: 0, on: null, native: null } },
    ],
  };

  it("shows each cell by its column's kind, right-aligns the numbers, and writes a missing cell as a dash", () => {
    render(<TableView {...props(["rows", "table"], rows, { title: "Detail" })} />);
    expect(screen.getByRole("heading", { name: "Detail" })).toBeTruthy();
    const alpha = within(screen.getByText("Alpha").closest("tr") as HTMLElement);
    expect(alpha.getByText("$2,500.00")).toBeTruthy();
    expect(alpha.getByText("3")).toBeTruthy();
    expect(alpha.getByText("EUR 372,000 (minor units)")).toBeTruthy();
    const beta = within(screen.getByText("Beta").closest("tr") as HTMLElement);
    expect(beta.getByText("-$125.00")).toBeTruthy();
    expect(beta.getAllByText("—")).toHaveLength(2);
    expect(screen.getByRole("columnheader", { name: "Value" }).className).toBe("r");
    expect(screen.getByRole("columnheader", { name: "Account" }).className).toBe("");
  });

  it("makes the first cell of a row with a drill target a link to it, and no other row", () => {
    render(<TableView {...props(["rows", "table"], rows)} />);
    expect(screen.getByRole("link", { name: "Alpha" }).getAttribute("href")).toBe("/accounts/5");
    expect(screen.queryByRole("link", { name: "Beta" })).toBeNull();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("says so when there are no rows, and still names the section", () => {
    render(<TableView {...props(["rows", "table"], { columns: rows.columns, rows: [] }, { title: "Detail" })} />);
    expect(screen.getByRole("heading", { name: "Detail" })).toBeTruthy();
    expect(screen.getByText("Nothing to list.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("a hierarchy drawn as a treemap", () => {
  const data: HierarchyData = { nodes: [
    { id: "a", label: "Savings", value: 59_000, size: 60_000, children: [{ id: "a1", label: "Emergency fund", value: 60_000, size: 60_000, link: { to: "account", id: 9 } }, { id: "a2", label: "Overdrawn", value: -1_000, size: 0 }] },
    { id: "b", label: "Checking", value: 30_000, size: 30_000 },
  ] };

  it("lists the nodes as buttons, largest first, with the value a person reads (signed, and not the area)", () => {
    render(<TreemapView {...props(["hierarchy", "treemap"], data, { title: "Assets", sized: true })} />);
    const list = within(screen.getByRole("list", { name: "Assets, as a list" }));
    expect(list.getAllByRole("button").map((b) => b.textContent)).toEqual(["Savings ▸$590.00", "Checking$300.00"]);       // the type's value is its signed sum, not its area
  });

  it("drills into a node, lists every account in it including the one that has no area, and hands a leaf's drill target over", () => {
    render(<TreemapView {...props(["hierarchy", "treemap"], data, { title: "Assets", sized: true })} />);
    fireEvent.click(screen.getByRole("button", { name: /^Savings/ }));
    const list = within(screen.getByRole("list", { name: "Assets, as a list" }));
    expect(list.getAllByRole("button").map((b) => b.textContent)).toEqual(["Emergency fund$600.00", "Overdrawn · not in the chart-$10.00"]);
    act(() => { fireEvent.click(list.getByRole("button", { name: /Emergency fund/ })); });
    expect(window.location.pathname).toBe("/accounts/9");
  });

  it("colours a node from the entity the report names, so an account takes its type's colour and not its own id's", () => {
    const coloured: HierarchyData = { nodes: [
      { id: "t7", label: "Savings", value: 600, size: 600, colour: { kind: "account_type", id: 7 }, children: [
        { id: "x31", label: "Joint", value: 600, size: 600, colour: { kind: "account_type", id: 7 }, link: { to: "account", id: 31 } }] },
      { id: "t18", label: "Cash", value: 100, size: 100, colour: { kind: "account_type", id: 18 } },
      { id: "t0", label: "Plain", value: 50, size: 50 }] };
    const { container } = render(<TreemapView {...props(["hierarchy", "treemap"], coloured, { title: "Assets", sized: true })} />);
    const swatches = [...container.querySelectorAll(".chart-list .chart-swatch")].map((s) => [...s.classList].find((c) => c.startsWith("chart-slot")));
    expect(swatches).toEqual(["chart-slot-7", "chart-slot-2", undefined]);                  // 18 repeats as 2, and a node with no colour is muted
    fireEvent.click(screen.getByRole("button", { name: /^Savings/ }));
    expect([...container.querySelectorAll(".chart-list .chart-swatch")].map((s) => [...s.classList].find((c) => c.startsWith("chart-slot")))).toEqual(["chart-slot-7"]);
  });

  it("says nothing but where you are when a hierarchy has no nodes, so a report can say why in a note", () => {
    const { container } = render(<TreemapView {...props(["hierarchy", "treemap"], { nodes: [] }, { title: "Liabilities", sized: true })} />);
    expect(screen.getByRole("navigation", { name: "Where you are in Liabilities" }).textContent).toBe("Liabilities");
    expect(container.querySelector(".chart-canvas")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("does nothing for a leaf that names no target", () => {
    render(<TreemapView {...props(["hierarchy", "treemap"], data, { title: "Assets", sized: true })} />);
    fireEvent.click(screen.getByRole("button", { name: /^Checking/ }));
    expect(window.location.pathname).toBe("/reports/probe");
  });
});

describe("a hierarchy drawn as a table", () => {
  const data: HierarchyData = { nodes: [
    { id: "a", label: "Savings", value: 59_000, children: [{ id: "a1", label: "Emergency fund", value: 60_000, link: { to: "account", id: 9 } }, { id: "a2", label: "Overdrawn", value: -1_000 }] },
    { id: "b", label: "Checking", value: 30_000 },
  ] };

  it("lists every node in order with its value, a child indented under its parent and a parent marked, and links a node that has a target", () => {
    render(<TableView {...props(["hierarchy", "table"], data, { title: "Assets" })} />);
    expect(screen.getByRole("heading", { name: "Assets" })).toBeTruthy();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(["▾ Savings$590.00", "Emergency fund$600.00", "Overdrawn-$10.00", "Checking$300.00"]);
    expect(rows.map((r) => r.className)).toEqual(["rp-parent", "", "", ""]);
    expect(rows[1].querySelector("span")!.className).toBe("rp-depth-1");
    expect(rows[0].querySelector("span")!.className).toBe("");
    expect(screen.getByRole("link", { name: "Emergency fund" }).getAttribute("href")).toBe("/accounts/9");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("columnheader", { name: "Value" }).className).toBe("r");
  });

  it("opens and closes a parent with a button that says which it is, and a parent with nothing in it has none", () => {
    render(<TableView {...props(["hierarchy", "table"], data, { title: "Assets" })} />);
    const toggle = () => screen.getByRole("button", { name: /Savings/ });
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle());
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Emergency fund")).toBeNull();
    expect(screen.getByText("Checking")).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(1);                      // Checking has nothing inside it
    fireEvent.click(toggle());
    expect(screen.getByText("Emergency fund")).toBeTruthy();
  });

  it("starts collapsed when the section says so, and keeps what a person opened when the report is worked out again", () => {
    const { rerender } = render(<TableView {...props(["hierarchy", "table"], data, { title: "Assets", expanded: false })} />);
    expect(screen.queryByText("Emergency fund")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Savings/ }));
    expect(screen.getByText("Emergency fund")).toBeTruthy();
    const again: HierarchyData = { nodes: [{ ...data.nodes[0], value: 59_500 }, data.nodes[1]] };
    rerender(<TableView {...props(["hierarchy", "table"], again, { title: "Assets", expanded: false })} />);
    expect(screen.getByText("Emergency fund")).toBeTruthy();                   // still open
    expect(screen.getByText("$595.00")).toBeTruthy();
  });

  describe("comparing two dates", () => {
    const compared: HierarchyData = { nodes: [
      { id: "t", label: "Savings", value: 1_500, opening: 10_000, closing: 11_500, note: "2 accounts", children: [
        { id: "a", label: "Alpha", value: 2_000, opening: 5_000, closing: 7_000, note: "1 Mar 2026 → 3 Jun 2026", link: { to: "account", id: 4 } },
        { id: "b", label: "Beta", value: -500, opening: 5_000, closing: 4_500, note: "No balance on 31 May 2026" }] },
    ] };
    const open = () => render(<TableView {...props(["hierarchy", "table"], compared, { title: "Detail", expanded: false })} />);

    it("shows the opening, closing and change of each node and the balances behind them, once a type is opened", () => {
      open();
      expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Type and account", "Opening", "Closing", "Change", "Balances used"]);
      expect(screen.getAllByRole("row").slice(1).map((r) => r.textContent)).toEqual(["▸ Savings$100.00$115.00+$15.002 accounts"]);
      fireEvent.click(screen.getByRole("button", { name: /Savings/ }));
      expect(screen.getAllByRole("row").slice(1).map((r) => r.textContent)).toEqual([
        "▾ Savings$100.00$115.00+$15.002 accounts", "Alpha$50.00$70.00+$20.001 Mar 2026 → 3 Jun 2026", "Beta$50.00$45.00-$5.00No balance on 31 May 2026"]);
      expect(screen.getByRole("link", { name: "Alpha" }).getAttribute("href")).toBe("/accounts/4");
    });

    it("colours a change by its direction and always writes its sign", () => {
      open();
      fireEvent.click(screen.getByRole("button", { name: /Savings/ }));
      const direction = (text: string) => screen.getByText(text).className;
      expect(direction("+$20.00")).toBe("p");
      expect(direction("-$5.00")).toBe("n");
      expect(direction("+$15.00")).toBe("p");
    });
  });

  it("says so when it is empty, and never needs the columns and rows of a table of rows", () => {
    render(<TableView {...props(["hierarchy", "table"], { nodes: [] }, { title: "Assets" })} />);
    expect(screen.getByText("Nothing to list.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("every view with every kind of section the server allows it", () => {
  const DATA: Record<string, ViewProps["data"]> = {
    summary: { items: [{ key: "n", label: "N", kind: "count", value: 1 }] },
    series: { series: [{ key: "s", label: "S", kind: "money", points: [{ x: "2026-01-01", value: 1 }] }] },
    hierarchy: { nodes: [{ id: "a", label: "A", value: 1, size: 1, children: [{ id: "a1", label: "A1", value: 1, size: 1 }] }] },
    rows: { columns: [{ key: "c", label: "C", kind: "text" }], rows: [{ id: "r", cells: { c: "x" } }] },
  };

  it("draws without failing, because a view is given the payload of the kind that names it and may be given more than one kind", () => {
    for (const [kind, views] of Object.entries(VIEWS)) {
      for (const view of views) {
        const View = VIEW_COMPONENTS[view];
        const { container } = render(<View {...props([kind as ReportSectionDeclaration["kind"], view], DATA[kind], { sized: kind === "hierarchy" })} />);
        expect(container.textContent, `${kind} as ${view}`).not.toBe("");
        cleanup();
      }
    }
  });
});


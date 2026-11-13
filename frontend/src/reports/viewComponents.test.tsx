// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { giveBoxesASize } from "../charts/chartTesting";
import { formatDate } from "../dates";
import { linkHref, TableView, TilesView, TreemapView, UnavailableView, VIEW_COMPONENTS, type ViewProps } from "./viewComponents";
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
  ({ key: "s", kind, view, title: "Section", sized: false, columns: 12, ...over });
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
    expect(list.getAllByRole("button").map((b) => b.textContent)).toEqual(["Emergency fund$600.00", "Overdrawn-$10.00"]);
    act(() => { fireEvent.click(list.getByRole("button", { name: /Emergency fund/ })); });
    expect(window.location.pathname).toBe("/accounts/9");
  });

  it("does nothing for a leaf that names no target", () => {
    render(<TreemapView {...props(["hierarchy", "treemap"], data, { title: "Assets", sized: true })} />);
    fireEvent.click(screen.getByRole("button", { name: /^Checking/ }));
    expect(window.location.pathname).toBe("/reports/probe");
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FieldNode, FieldTree, ListColumn, ListPage, ListRequest, ListRow } from "./api";
import { ListView } from "./ListView";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn(), fetchListFields: vi.fn(), fetchListChoices: vi.fn(),
  fetchSavedFilters: vi.fn(),
}));

import { fetchList, fetchListChoices, fetchListFields, fetchSavedFilters } from "./api";

const col = (key: string, path_label: string, kind: ListColumn["kind"], over: Partial<ListColumn> = {}): ListColumn =>
  ({ key, label: path_label.split(" › ").pop()!, path_label, kind, scale: null, linked: false, groupable: true, ...over });
const COLUMNS = [col("as_of_date", "Date", "date"), col("account", "Account", "text"), col("account.type", "Account › Type", "text"),
  col("amount_cents", "Value", "amount", { groupable: false }), col("note", "Note", "text")];
const node = (c: ListColumn): FieldNode => ({ key: c.key, label: c.label, path_label: c.path_label, kind: c.kind, scale: null, operators: [], choices: null });
const TREE: FieldTree = { fields: COLUMNS.map(node), relations: [] };

/** A grouped row, as the server answers it. */
const row = (id: number, group: unknown, count: number, before = 0): ListRow => ({
  _id: id, _links: {}, as_of_date: "2026-05-01", account: `Test account ${id}`, "account.type": String(group ?? ""), amount_cents: { value: 100, scale: 2, unit: "USD" },
  note: null, _group: group, _group_count: count, _group_before: before,
});

// Fourteen rows: Checking 3, Credit card 2, Savings 9, in that order, ten to a page.
const FIRST = [row(1, "Checking", 3), row(2, "Checking", 3, 1), row(3, "Checking", 3, 2), row(4, "Credit card", 2), row(5, "Credit card", 2, 1),
  row(6, "Savings", 9), row(7, "Savings", 9, 1), row(8, "Savings", 9, 2), row(9, "Savings", 9, 3), row(10, "Savings", 9, 4)];
const SECOND = [row(11, "Savings", 9, 5), row(12, "Savings", 9, 6), row(13, "Savings", 9, 7), row(14, "Savings", 9, 8)];

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: [], total: 14, page: 1, pages: 2, page_size: 10, group: null, sort: { field: "as_of_date", direction: "desc" },
  filters: [], skipped: [], default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [], ...over,
});

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);
const here = () => window.location.pathname + window.location.search;
const headers = () => screen.queryAllByRole("button", { expanded: true }).concat(screen.queryAllByRole("button", { expanded: false })).filter((b) => b.classList.contains("grp-btn"));
const groupTexts = () => [...document.querySelectorAll(".grp-btn")].map((b) => b.textContent?.replace(/[▾▸]/g, "").trim());
const bodyRows = () => document.querySelectorAll("tr.row").length;
const openMenu = async (label: string) => fireEvent.click(await screen.findByRole("button", { name: `Column menu for ${label}` }));
const menuItems = () => within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent);

/** The server's answer to a grouped request: this page's rows, by the page asked for. */
const grouped = (request: ListRequest, group: string | null = request.group ?? null) => {
  if (!group) return page({ rows: [row(1, "x", 1)], group: null });
  const second = (request.page ?? 1) === 2;
  return page({ rows: second ? SECOND : FIRST, page: second ? 2 : 1, group });
};

beforeEach(() => {
  window.history.replaceState(null, "", "/balances?group=account.type");
  vi.mocked(fetchList).mockImplementation(async (_key, request) => grouped(request));
  vi.mocked(fetchListFields).mockResolvedValue(TREE);
  vi.mocked(fetchListChoices).mockResolvedValue({ kind: "values", values: [], more: false, options: [] });
  vi.mocked(fetchSavedFilters).mockResolvedValue({ filters: [], default_id: null });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the header menu", () => {
  it("offers Group by on a column that can be grouped, and not on an amount", async () => {
    window.history.replaceState(null, "", "/balances");
    render(<ListView listKey="balances" />);
    await openMenu("Account");
    expect(menuItems()).toEqual(["Sort ascending", "Sort descending", "Group by Account"]);
    fireEvent.keyDown(document, { key: "Escape" });
    await openMenu("Value");
    expect(menuItems()).toEqual(["Sort ascending", "Sort descending"]);
  });

  it("offers, on the column the list is grouped by, Expand all, Collapse all and Ungroup after the sorts, and no Group by", async () => {
    render(<ListView listKey="balances" />);
    await openMenu("Account › Type");
    expect(menuItems()).toEqual(["Sort ascending", "Sort descending", "Expand all", "Collapse all", "Ungroup"]);
  });

  it("offers Group by on another column while the list is grouped, which switches the grouping", async () => {
    render(<ListView listKey="balances" />);
    await openMenu("Account");
    expect(menuItems()).toEqual(["Sort ascending", "Sort descending", "Group by Account"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Group by Account" }));
    await waitFor(() => expect(requests().at(-1)?.group).toBe("account"));
    expect(here()).toBe("/balances?group=account");
  });

  it("groups by the column chosen, writes it in the address and goes back to the first page", async () => {
    window.history.replaceState(null, "", "/balances?page=3");
    render(<ListView listKey="balances" />);
    await openMenu("Account › Type");
    fireEvent.click(screen.getByRole("menuitem", { name: "Group by Account › Type" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, group: "account.type" }));
    expect(here()).toBe("/balances?group=account.type");
  });

  it("ungroups from the menu, and the address is plain again", async () => {
    render(<ListView listKey="balances" />);
    await openMenu("Account › Type");
    fireEvent.click(screen.getByRole("menuitem", { name: "Ungroup" }));
    await waitFor(() => expect("group" in requests().at(-1)!).toBe(false));
    expect(here()).toBe("/balances");
    expect(document.querySelector(".grp-btn")).toBeNull();
  });
});

describe("a grouped list", () => {
  it("shows a header for each group with its name and its count, the rows under it, and the footer counting rows as it does for a flat list", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    expect(groupTexts()).toEqual(["Checking3 rows", "Credit card2 rows", "Savings9 rows (5 on this page)"]);
    expect(bodyRows()).toBe(10);
    expect(screen.getByText("1–10 of 14")).toBeTruthy();
    expect(headers().every((h) => h.getAttribute("aria-expanded") === "true")).toBe(true);
  });

  it("marks a group that continues from the page before, with its size and how many of its rows are on this page", async () => {
    window.history.replaceState(null, "", "/balances?group=account.type&page=2");
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(1));
    expect(groupTexts()).toEqual(["Savings9 rows (4 on this page)continued"]);
    expect(screen.getByText("11–14 of 14")).toBeTruthy();
  });

  it("does not mark the first page's last group as continued, though it goes on to the next page", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    expect(screen.queryByText("continued")).toBeNull();
  });

  it("calls a group with no value No value, and a value the way its column writes it", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ group: "as_of_date", total: 3,
      rows: [{ ...row(1, "2026-04-20", 2), _group: "2026-04-20" }, { ...row(2, "2026-04-20", 2, 1), _group: "2026-04-20" }, row(3, null, 1)] }));
    window.history.replaceState(null, "", "/balances?group=as_of_date");
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(2));
    expect(groupTexts()).toEqual(["Apr 20, 20262 rows", "No value1 row"]);
  });

  it("shows a group by a column that is not among the shown columns, named from the list of columns it can offer", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ columns: COLUMNS.slice(0, 2), rows: FIRST.slice(0, 5), group: "account.type" }));
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(2));
    expect(screen.getByText("Grouped by Account › Type")).toBeTruthy();
  });

  it("keeps the grouping when the sort changes, and sorts by the column asked for", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("button", { name: "Date" });
    fireEvent.click(screen.getByRole("button", { name: "Date" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, group: "account.type", sort: { field: "as_of_date", direction: "asc" } }));
    expect(here()).toContain("group=account.type");
  });
});

describe("the chip", () => {
  it("says what the list is grouped by, and removes the grouping", async () => {
    render(<ListView listKey="balances" />);
    expect(await screen.findByText("Grouped by Account › Type")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ungroup" }));
    await waitFor(() => expect(here()).toBe("/balances"));
    expect(screen.queryByText(/Grouped by/)).toBeNull();
  });

  it("is there when the list could not be loaded, so a grouping the server refused can be removed", async () => {
    vi.mocked(fetchList).mockRejectedValue(new Error("Value cannot be grouped."));
    window.history.replaceState(null, "", "/balances?group=amount_cents");
    render(<ListView listKey="balances" />);
    expect(await screen.findByText(/Could not load the list\. Value cannot be grouped\./)).toBeTruthy();
    expect(screen.getByText("Grouped by Value")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ungroup" }));
    await waitFor(() => expect(here()).toBe("/balances"));
  });

  it("is not there for a list that is not grouped", async () => {
    window.history.replaceState(null, "", "/balances");
    render(<ListView listKey="balances" />);
    await screen.findByRole("button", { name: "Filters" });
    expect(screen.queryByText(/Grouped by/)).toBeNull();
  });
});

describe("collapsing", () => {
  const header = (name: string) => [...document.querySelectorAll(".grp-btn")].find((b) => b.textContent?.includes(name)) as HTMLButtonElement;

  it("hides a group's rows when its header is pressed, and shows them when it is pressed again, and the footer counts the same rows", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    fireEvent.click(header("Checking"));
    expect(header("Checking").getAttribute("aria-expanded")).toBe("false");
    expect(bodyRows()).toBe(7);
    expect(header("Savings").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("1–10 of 14")).toBeTruthy();
    fireEvent.click(header("Checking"));
    expect(bodyRows()).toBe(10);
  });

  it("keeps a group collapsed when the page changes, within the visit", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    fireEvent.click(header("Savings"));
    expect(bodyRows()).toBe(5);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("11–14 of 14")).toBeTruthy());
    expect(header("Savings").getAttribute("aria-expanded")).toBe("false");
    expect(bodyRows()).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(screen.getByText("1–10 of 14")).toBeTruthy());
    expect(header("Savings").getAttribute("aria-expanded")).toBe("false");        // and back again
  });

  it("collapses every group from the menu, those on the next page too, and opens them all again", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    await openMenu("Account › Type");
    fireEvent.click(screen.getByRole("menuitem", { name: "Collapse all" }));
    expect(bodyRows()).toBe(0);
    expect(screen.queryByRole("menu")).toBeNull();                                  // the menu closes
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("11–14 of 14")).toBeTruthy());
    expect(header("Savings").getAttribute("aria-expanded")).toBe("false");          // a group the page had not seen is collapsed too
    fireEvent.click(header("Savings"));                                             // and one can be opened by itself
    expect(bodyRows()).toBe(4);
    fireEvent.click(await screen.findByRole("button", { name: "Column menu for Account › Type" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Expand all" }));
    expect(bodyRows()).toBe(4);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(screen.getByText("1–10 of 14")).toBeTruthy());
    expect(headers().every((h) => h.getAttribute("aria-expanded") === "true")).toBe(true);
    expect(bodyRows()).toBe(10);
  });

  it("opens every group again when the grouping changes", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    fireEvent.click(header("Checking"));
    expect(bodyRows()).toBe(7);
    await openMenu("Account");
    fireEvent.click(screen.getByRole("menuitem", { name: "Group by Account" }));
    await waitFor(() => expect(requests().at(-1)?.group).toBe("account"));
    await waitFor(() => expect(bodyRows()).toBe(10));
  });

  it("is not in the address, so a copied link opens every group", async () => {
    render(<ListView listKey="balances" />);
    await waitFor(() => expect(groupTexts()).toHaveLength(3));
    fireEvent.click(header("Checking"));
    expect(here()).toBe("/balances?group=account.type");
  });
});

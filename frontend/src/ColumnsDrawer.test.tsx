// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FieldNode, FieldTree, ListColumn, ListPage } from "./api";
import { ListView } from "./ListView";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn(), fetchListFields: vi.fn(), fetchListChoices: vi.fn(),
  fetchSavedFilters: vi.fn(), saveListColumns: vi.fn(),
}));

import { fetchList, fetchListChoices, fetchListFields, fetchSavedFilters, saveListColumns } from "./api";

const column = (key: string, label: string, path_label = label): ListColumn => ({ key, label, path_label, kind: "text", scale: null, linked: false });
const COLUMNS = [column("as_of_date", "Date"), column("account", "Account"), column("amount_cents", "Value")];
const field = (over: Partial<FieldNode>): FieldNode => ({ key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: [{ name: "equals", label: "equals" }], choices: null, ...over });

const TREE: FieldTree = {
  fields: [
    field({ key: "note", label: "Note", path_label: "Note" }),
    field({ key: "as_of_date", label: "Date", path_label: "Date", kind: "date" }),
    field({ key: "amount_cents", label: "Value", path_label: "Value", kind: "amount" }),
  ],
  relations: [
    field({
      key: "account", label: "Account", path_label: "Account", kind: "choice", choices: "records",
      children: { fields: [field({ key: "account.name", label: "Name", path_label: "Account › Name" }), field({ key: "account.currency", label: "Currency", path_label: "Account › Currency" })], relations: [] },
    }),
  ],
};

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: [{ _id: 1, _links: {}, as_of_date: "2026-05-31", account: "Test account 1", amount_cents: 100 }], total: 1, page: 1, pages: 1, page_size: 25,
  group: null, sort: { field: "as_of_date", direction: "desc" }, filters: [], skipped: [], default_filter_id: null,
  default_columns: ["as_of_date", "account", "amount_cents"], customised: false, skipped_columns: [], ...over,
});

const open = async () => { fireEvent.click(await screen.findByRole("button", { name: "Columns" })); return screen.findByRole("dialog"); };
const drawer = () => within(screen.getByRole("dialog"));
const order = () => within(drawer().getByRole("list", { name: "Columns shown" })).getAllByRole("listitem").map((item) => item.querySelector(".lc-name")?.firstChild?.textContent);
const button = (name: string) => drawer().getByRole("button", { name }) as HTMLButtonElement;
const apply = () => fireEvent.click(button("Apply changes"));

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(fetchListFields).mockResolvedValue(TREE);
  vi.mocked(fetchListChoices).mockResolvedValue({ kind: "records", values: [], more: false, options: [] });
  vi.mocked(fetchSavedFilters).mockResolvedValue({ filters: [], default_id: null });
  vi.mocked(saveListColumns).mockImplementation(async (_key, columns) => ({ columns: columns ?? [], customised: columns !== null }));
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the columns tab of the drawer", () => {
  it("opens from the Columns button on the Columns tab, with the columns in the order the list shows them", async () => {
    render(<ListView listKey="balances" config={{ title: "Balances" }} />);
    const dialog = await open();
    expect(within(dialog).getByRole("button", { name: "Columns (3)" }).getAttribute("aria-current")).toBe("true");
    expect(order()).toEqual(["Date", "Account", "Value"]);
    expect(within(dialog).getByRole("button", { name: "Filters (0)" }).getAttribute("aria-current")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Filters (0)" }));
    expect(within(dialog).getByText("No conditions. Every row is shown.")).toBeTruthy();    // the filters are one click away
  });

  it("says a related column by its name and, in small type, where it comes from", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ columns: [column("account.name", "Name", "Account › Name")], default_columns: ["account.name"] }));
    render(<ListView listKey="balances" />);
    await open();
    expect(drawer().getByText("Name").querySelector("small")?.textContent).toBe("Account");
    expect(drawer().getByRole("button", { name: "Move Account › Name up" })).toBeTruthy();
  });

  it("moves a column with the arrows, keeps the ends from moving off, and changes nothing until Apply", async () => {
    render(<ListView listKey="balances" />);
    await open();
    expect(button("Move Date up").disabled).toBe(true);
    expect(button("Move Value down").disabled).toBe(true);
    fireEvent.click(button("Move Date down"));
    expect(order()).toEqual(["Account", "Date", "Value"]);
    fireEvent.click(button("Move Value up"));
    expect(order()).toEqual(["Account", "Value", "Date"]);
    expect(saveListColumns).not.toHaveBeenCalled();
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalledWith("balances", ["account", "amount_cents", "as_of_date"]));
    await waitFor(() => expect(vi.mocked(fetchList).mock.calls.length).toBe(2));             // the list is asked again, to show them
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("saves nothing when Apply is pressed with the columns as they were", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Move Date down"));
    fireEvent.click(button("Move Date up"));
    apply();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(saveListColumns).not.toHaveBeenCalled();
  });

  it("throws the changes away on Cancel and on Escape", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Remove Value"));
    fireEvent.click(button("Cancel"));
    expect(screen.queryByRole("dialog")).toBeNull();
    await open();
    expect(order()).toEqual(["Date", "Account", "Value"]);
    fireEvent.click(button("Remove Value"));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(saveListColumns).not.toHaveBeenCalled();
  });

  it("removes a column, and keeps the last one: it cannot be removed and the drawer says why", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ columns: COLUMNS.slice(0, 2) }));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Remove Date"));
    expect(order()).toEqual(["Account"]);
    expect(button("Remove Account").disabled).toBe(true);
    expect(drawer().getByText("At least one column stays, so the list is never empty.")).toBeTruthy();
    fireEvent.click(button("Remove Account"));
    expect(order()).toEqual(["Account"]);
  });

  it("adds a column from the same tree as the filters, at the end, and greys out the ones already shown", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("+ Add column"));
    const picker = within(drawer().getByLabelText("Columns to show"));
    expect((picker.getByRole("button", { name: "Date" }) as HTMLButtonElement).disabled).toBe(true);
    expect(picker.queryByText(/shown|already/)).toBeNull();                                     // grey is enough
    fireEvent.click(picker.getByRole("button", { name: "Show the columns of Account" }));
    expect((picker.getByRole("button", { name: "Currency" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(picker.getByRole("button", { name: "Currency" }));
    expect(order()).toEqual(["Date", "Account", "Value", "Currency"]);
    expect(drawer().queryByLabelText("Columns to show")).toBeNull();                              // the picker closes
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalledWith("balances", ["as_of_date", "account", "amount_cents", "account.currency"]));
  });

  it("resets to the list's own columns: enabled only once they differ, and applying forgets the choice", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ columns: [COLUMNS[2], COLUMNS[0]], customised: true }));
    render(<ListView listKey="balances" />);
    await open();
    expect(order()).toEqual(["Value", "Date"]);
    fireEvent.click(button("Reset to default columns"));
    expect(order()).toEqual(["Date", "Account", "Value"]);
    expect(button("Reset to default columns").disabled).toBe(true);
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalledWith("balances", null));
  });

  it("has nothing to reset to while the columns are the list's own", async () => {
    render(<ListView listKey="balances" />);
    await open();
    expect(button("Reset to default columns").disabled).toBe(true);
    fireEvent.click(button("Move Date down"));
    expect(button("Reset to default columns").disabled).toBe(false);
  });

  it("forgets the choice rather than saving it when the person puts the columns back to the list's own", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ columns: [COLUMNS[1], COLUMNS[0], COLUMNS[2]], customised: true }));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Move Account down"));
    expect(order()).toEqual(["Date", "Account", "Value"]);
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalledWith("balances", null));
  });

  it("says a saved column the list no longer offers, on the page and in the drawer, and saving leaves it out", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ skipped_columns: [{ field: "account.currency", reason: "That column does not exist." }], customised: true }));
    render(<ListView listKey="balances" />);
    expect((await screen.findByText(/1 column of your choice was left out/)).getAttribute("role")).toBe("status");
    await open();
    expect(drawer().getByText(/“Account › Currency” is not offered by this list any more/)).toBeTruthy();
  });

  it("sends the person to the filters when Apply is pressed while a condition is incomplete, and saves nothing yet", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(drawer().getByRole("button", { name: "Filters (0)" }));
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(drawer().getByLabelText("Columns to filter by")).getByRole("button", { name: "Note" }));
    fireEvent.click(drawer().getByRole("button", { name: "Columns (3)" }));
    fireEvent.click(button("Move Date down"));
    apply();
    expect(drawer().getByText(/Complete or remove the conditions/)).toBeTruthy();
    expect(drawer().getByRole("button", { name: "Filters (1)" }).getAttribute("aria-current")).toBe("true");
    expect(saveListColumns).not.toHaveBeenCalled();
  });

  it("applies the filters and the columns together", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Remove Value"));
    fireEvent.click(drawer().getByRole("button", { name: "Filters (0)" }));
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(drawer().getByLabelText("Columns to filter by")).getByRole("button", { name: "Note" }));
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalledWith("balances", ["as_of_date", "account"]));
    expect(window.location.search).toContain("filters=");
  });

  it("leaves the address alone when only the columns changed, so a default filter stays the default and does not become a written one", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [{ field: "note", operator: "equals", value: "rent" }], default_filter_id: 7 }));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Remove Value"));
    apply();
    await waitFor(() => expect(saveListColumns).toHaveBeenCalled());
    await waitFor(() => expect(vi.mocked(fetchList).mock.calls.length).toBe(2));
    expect(window.location.pathname + window.location.search).toBe("/balances");
    expect(vi.mocked(fetchList).mock.calls.every((call) => !("filters" in (call[1] as object)))).toBe(true);     // the server still applies the default
  });

  it("says when the columns could not be saved, and keeps the list as it was", async () => {
    vi.mocked(saveListColumns).mockRejectedValue(new Error("Choose at least one column."));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(button("Remove Value"));
    apply();
    expect((await screen.findByRole("alert")).textContent).toBe("The columns could not be saved. Choose at least one column.");
    expect(vi.mocked(fetchList).mock.calls.length).toBe(1);
  });

  it("gives every row a handle to drag it by, named for its column, and the arrows work for those who cannot drag", async () => {
    render(<ListView listKey="balances" />);
    await open();
    const handle = button("Drag Account to move it");
    expect(handle.getAttribute("aria-roledescription")).toBe("sortable");
    expect(handle.getAttribute("tabindex")).toBe("0");
  });
});

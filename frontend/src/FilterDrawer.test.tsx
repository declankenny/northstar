// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Condition, FieldNode, FieldTree, ListColumn, ListPage, ListRequest, SavedFilter, SavedFilters } from "./api";
import { ListView } from "./ListView";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn(), fetchListFields: vi.fn(), fetchListChoices: vi.fn(),
  fetchSavedFilters: vi.fn(), saveSavedFilter: vi.fn(), changeSavedFilter: vi.fn(), deleteSavedFilter: vi.fn(),
}));

import {
  changeSavedFilter, deleteSavedFilter, fetchList, fetchListChoices, fetchListFields, fetchSavedFilters, saveListPageSize, saveSavedFilter,
} from "./api";

const COLUMNS: ListColumn[] = [
  { key: "account", label: "Account", path_label: "Account", kind: "text", scale: null, linked: false, groupable: true },
  { key: "as_of_date", label: "Date", path_label: "Date", kind: "date", scale: null, linked: false, groupable: true },
];
const LABELS: Record<string, string> = { is_any_of: "is one of", is_not_any_of: "is not one of", is_not: "is not", is: "is" };   // as the server words them
const ops = (...names: string[]) => names.map((name) => ({ name, label: LABELS[name] ?? name.replaceAll("_", " ") }));
const field = (over: Partial<FieldNode>): FieldNode => ({ key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: ops("equals"), choices: null, ...over });

const TREE: FieldTree = {
  fields: [
    field({ key: "note", label: "Note", path_label: "Note", operators: ops("contains", "equals", "is_empty", "is_not_empty") }),
    field({ key: "as_of_date", label: "Date", path_label: "Date", kind: "date", operators: ops("before", "after", "between", "is_empty") }),
    field({ key: "amount_cents", label: "Value", path_label: "Value", kind: "amount", operators: ops("equals", "at_least", "at_most", "between", "is_empty") }),
  ],
  relations: [
    field({
      key: "account", label: "Account", path_label: "Account", kind: "choice", operators: ops("is_any_of"), choices: "records",
      children: { fields: [field({ key: "account.status", label: "Status", path_label: "Account › Status", kind: "choice", operators: ops("is_any_of"), choices: "values", values: ["Open", "Closed"] })], relations: [] },
    }),
  ],
};

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: [{ _id: 1, _links: {}, account: "Test account 1", as_of_date: "2026-05-31" }], total: 1, page: 1, pages: 1, page_size: 25,
  group: null, sort: { field: "as_of_date", direction: "desc" }, filters: [], skipped: [], default_filter_id: null,
  default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [], ...over,
});

const filter = (id: number, name: string, over: Partial<SavedFilter> = {}): SavedFilter => ({
  id, name, shared: false, is_default: false, can_edit: true, conditions: [], problems: [], ...over,
});
const set = (filters: SavedFilter[], default_id: number | null = null): SavedFilters => ({ filters, default_id });

const NOTE: Condition = { field: "note", operator: "contains", value: "rent" };
const AFTER: Condition = { field: "as_of_date", operator: "after", value: "2025-12-31" };

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);
const here = () => window.location.pathname + window.location.search;
const open = async () => { fireEvent.click(await screen.findByRole("button", { name: /^Filters/ })); return screen.findByRole("dialog"); };
const drawer = () => within(screen.getByRole("dialog"));
const addFilter = (name: string) => {
  fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
  fireEvent.click(within(drawer().getByLabelText("Columns to filter by")).getByRole("button", { name }));
};
const apply = () => fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(saveListPageSize).mockImplementation(async (_key, size) => size);
  vi.mocked(fetchListFields).mockResolvedValue(TREE);
  vi.mocked(fetchListChoices).mockResolvedValue({ kind: "records", values: [], more: false, options: [{ id: 3, value: "Test dollars", detail: null }, { id: 4, value: "Test euros", detail: "EUR" }] });
  vi.mocked(fetchSavedFilters).mockResolvedValue(set([]));
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the filter drawer", () => {
  it("opens from the Filters button as a dialog with nothing applied, and has no chips", async () => {
    render(<ListView listKey="balances" config={{ title: "Balances" }} />);
    const dialog = await open();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(within(dialog).getByText("No conditions. Every row is shown.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Filters applied" })).toBeNull();
  });

  it("builds a condition from a column of the list, applies it with the address and the request, and shows a chip", async () => {
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [NOTE] }));
    expect(here()).toBe(`/balances?filters=${encodeURIComponent(JSON.stringify([NOTE]))}`);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows what is applied as chips and a count, named from the list's own answer", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [NOTE, AFTER] }));
    render(<ListView listKey="balances" />);
    const chips = await screen.findByRole("list", { name: "Filters applied" });
    expect(within(chips).getAllByRole("listitem").map((c) => c.firstChild?.textContent)).toEqual(["Note contains rent", "Date after Dec 31, 2025"]);
    expect(screen.getByRole("button", { name: "Filters (2)" })).toBeTruthy();
  });

  it("removes one chip at once, and clears them all as a filter cleared on purpose", async () => {
    window.history.replaceState(null, "", `/balances?filters=${encodeURIComponent(JSON.stringify([NOTE, AFTER]))}`);
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [NOTE, AFTER] }));
    render(<ListView listKey="balances" />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove the filter: Note contains rent" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [AFTER] }));
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [] }));
    expect(here()).toBe("/balances?filters=%5B%5D");
  });

  it("goes back to the first page when the filters change", async () => {
    window.history.replaceState(null, "", "/balances?page=3");
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    apply();
    await waitFor(() => expect(requests().at(-1)?.page).toBe(1));
    expect(here()).not.toContain("page=");
  });

  it("throws the draft away on Cancel and on Escape, and puts focus back on the button that opened it", async () => {
    render(<ListView listKey="balances" />);
    const button = await screen.findByRole("button", { name: "Filters" });
    await open();
    addFilter("Note");
    fireEvent.click(drawer().getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
    expect(here()).toBe("/balances");
    await open();
    expect(drawer().getByText("No conditions. Every row is shown.")).toBeTruthy();       // the draft did not survive
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("starts the draft from what is applied", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [AFTER] }));
    render(<ListView listKey="balances" />);
    await open();
    expect((drawer().getByLabelText("Date") as HTMLInputElement).value).toBe("2025-12-31");
    expect((drawer().getByLabelText("How to compare Date") as HTMLSelectElement).value).toBe("after");
  });

  it("offers every column once, a relation's own columns under it, and refuses a second condition on one column", async () => {
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    const picker = within(drawer().getByLabelText("Columns to filter by"));
    expect(picker.queryByRole("button", { name: "Status" })).toBeNull();                       // not until its relation is opened
    fireEvent.click(picker.getByRole("button", { name: "Show the columns of Account" }));
    fireEvent.click(picker.getByRole("button", { name: "Status" }));
    expect(drawer().getByLabelText("How to compare Account › Status")).toBeTruthy();
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    const again = within(drawer().getByLabelText("Columns to filter by"));
    expect((again.getByRole("button", { name: "Date" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(again.getByRole("button", { name: "Date" }));
    fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
    expect((within(drawer().getByLabelText("Columns to filter by")).getByRole("button", { name: "Date" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("chooses among declared values and among the records the list points at, sent as their ids", async () => {
    vi.mocked(fetchList).mockImplementation(async (_key, request) => page({ filters: request.filters ?? [] }));      // the server answers with what was asked
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Account");
    fireEvent.click(await drawer().findByRole("checkbox", { name: /Test euros/ }));
    fireEvent.click(drawer().getByRole("checkbox", { name: "Test dollars" }));
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [{ field: "account", operator: "is_any_of", value: [4, 3] }] }));
    expect(await screen.findByText("Account is one of Test euros, Test dollars")).toBeTruthy();    // the chip names them
  });

  it("takes a range as two boxes and keeps Apply off until it is a real range", async () => {
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Value");
    fireEvent.change(drawer().getByLabelText("How to compare Value"), { target: { value: "between" } });
    expect(drawer().queryByText("Type a number.")).toBeNull();                        // a new row is not nagged before it is tried
    apply();
    expect(drawer().getByText("Type a number.")).toBeTruthy();                         // trying shows what is missing
    expect(drawer().getByText(/Complete or remove the conditions/)).toBeTruthy();
    expect(requests()).toHaveLength(1);                                                // and applies nothing
    fireEvent.change(drawer().getByLabelText("Value, from"), { target: { value: "10" } });
    fireEvent.change(drawer().getByLabelText("Value, to"), { target: { value: "5" } });
    expect(drawer().getByText("The range ends before it starts.")).toBeTruthy();       // typed in, so said at once
    apply();
    expect(requests()).toHaveLength(1);
    fireEvent.change(drawer().getByLabelText("Value, to"), { target: { value: "10.5" } });
    expect(drawer().queryByText("The range ends before it starts.")).toBeNull();
    expect(drawer().queryByText(/Complete or remove the conditions/)).toBeNull();
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "amount_cents", operator: "between", value: ["10", "10.5"] }]));
  });

  it("drops the value when the operator takes none, and sends no value", async () => {
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    fireEvent.change(drawer().getByLabelText("How to compare Note"), { target: { value: "is_empty" } });
    expect(drawer().queryByLabelText("Note")).toBeNull();
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "note", operator: "is_empty" }]));
  });

  it("clears the draft with Clear filters, which applies only on Apply", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [NOTE] }));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(drawer().getByRole("button", { name: "Clear filters" }));
    expect(here()).toBe("/balances");
    apply();
    await waitFor(() => expect(here()).toBe("/balances?filters=%5B%5D"));
  });

  it("says a column that the list no longer offers is gone, and will not apply it", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [{ field: "region", operator: "equals", value: "x" }] }));
    render(<ListView listKey="balances" />);
    await open();
    expect(drawer().getByText("not a column of this list")).toBeTruthy();
    apply();
    expect(requests()).toHaveLength(1);                                                // it is not applied
    fireEvent.click(drawer().getByRole("button", { name: "Remove the filter on region" }));
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [] }));
  });
});

describe("a list's default filter", () => {
  it("shows the default's conditions as chips although the address names none, and says which was applied", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ filters: [AFTER], default_filter_id: 7 }));
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([filter(7, "Recent", { is_default: true, conditions: [AFTER] })], 7));
    render(<ListView listKey="balances" />);
    expect(await screen.findByText("Date after Dec 31, 2025")).toBeTruthy();
    expect(here()).toBe("/balances");
    expect(requests().at(-1)).toEqual({ page: 1 });                      // the request names no filters: the server applies the default
    await open();
    expect((await drawer().findByRole("button", { name: /Recent/ })).textContent).toContain("Recent");     // shown as loaded
  });

  it("does not bring the default back once it has been cleared on purpose", async () => {
    window.history.replaceState(null, "", "/balances?filters=%5B%5D");
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    expect(requests().at(-1)).toEqual({ page: 1, filters: [] });
  });

  it("says when conditions of the default no longer fit the list and were left out", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ skipped: [{ field: "region", reason: "region is not a column" }], default_filter_id: 7 }));
    render(<ListView listKey="balances" />);
    expect((await screen.findByRole("status")).textContent).toContain("1 condition of your default filter was left out");
  });

  it("offers to clear the filters when they leave nothing to show", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ rows: [], total: 0, pages: 1, filters: [NOTE] }));
    render(<ListView listKey="balances" />);
    fireEvent.click(await screen.findByRole("button", { name: "Clear the filters" }));
    await waitFor(() => expect(here()).toBe("/balances?filters=%5B%5D"));
  });
});

describe("saved filters", () => {
  const MINE = filter(1, "Rent notes", { conditions: [NOTE] });
  const SHARED = filter(2, "Recent", { shared: true, can_edit: false, conditions: [AFTER], is_default: true });

  it("lists the shared ones apart from the person's own, with their defaults marked", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE, { ...filter(3, "Mine too"), is_default: true }, SHARED], 3));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    const menu = within(drawer().getByRole("menu"));
    expect(menu.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Recent · default for everyone", "Rent notes", "Mine too · my default ★", "No saved filter"]);
  });

  it("only fills the draft when one is chosen: nothing is applied until Apply changes", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    expect((drawer().getByLabelText("Note") as HTMLInputElement).value).toBe("rent");
    expect(requests()).toHaveLength(1);                                    // only the first load
    expect(here()).toBe("/balances");
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [NOTE] }));    // the address carries conditions, never the saved filter
  });

  it("can be edited like any other draft, and says it has changed", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    const save = () => drawer().getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save().disabled).toBe(true);                                    // nothing to save yet
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "mortgage" } });
    expect(drawer().getByRole("button", { name: /Rent notes/ }).textContent).toContain("changed");
    expect(save().disabled).toBe(false);
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    expect(save().disabled).toBe(true);                                    // typed back to what it was
  });

  it("saves the draft over the loaded filter, and nothing else about it", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    vi.mocked(changeSavedFilter).mockResolvedValue(set([filter(1, "Rent notes", { conditions: [{ ...NOTE, value: "mortgage" }] })]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "mortgage" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(changeSavedFilter).toHaveBeenCalledWith("balances", 1, { conditions: [{ ...NOTE, value: "mortgage" }] }));
    await waitFor(() => expect((drawer().getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true));
    expect(requests()).toHaveLength(1);                                    // saving does not apply
  });

  it("saves a new filter under a name, private unless an admin says for everyone, and loads it", async () => {
    vi.mocked(saveSavedFilter).mockResolvedValue(set([filter(9, "Rent only", { conditions: [NOTE] })]));
    render(<ListView listKey="balances" config={{ isAdmin: false }} />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save as new…" }));
    expect(drawer().queryByRole("checkbox", { name: /For everyone/ })).toBeNull();           // admins only
    fireEvent.change(drawer().getByLabelText("Name for the new filter"), { target: { value: "Rent only" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save filter" }));
    await waitFor(() => expect(saveSavedFilter).toHaveBeenCalledWith("balances", { name: "Rent only", conditions: [NOTE], shared: false }));
    expect((await drawer().findByRole("button", { name: /Rent only/ })).textContent).toContain("Rent only");
    expect(drawer().queryByLabelText("Name for the new filter")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();                       // saving does not close the drawer or apply
    expect(requests()).toHaveLength(1);
  });

  it("lets an admin save for everyone, and make the new one the default in the same step", async () => {
    vi.mocked(saveSavedFilter).mockResolvedValue(set([filter(9, "Rent only", { shared: true, conditions: [NOTE] })]));
    vi.mocked(changeSavedFilter).mockResolvedValue(set([filter(9, "Rent only", { shared: true, is_default: true, conditions: [NOTE] })], 9));
    render(<ListView listKey="balances" config={{ isAdmin: true }} />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save as new…" }));
    fireEvent.change(drawer().getByLabelText("Name for the new filter"), { target: { value: "Rent only" } });
    fireEvent.click(drawer().getByRole("checkbox", { name: /For everyone/ }));
    fireEvent.click(drawer().getByRole("checkbox", { name: /Make it my default/ }));
    fireEvent.click(drawer().getByRole("button", { name: "Save filter" }));
    await waitFor(() => expect(saveSavedFilter).toHaveBeenCalledWith("balances", { name: "Rent only", conditions: [NOTE], shared: true }));
    await waitFor(() => expect(changeSavedFilter).toHaveBeenCalledWith("balances", 9, { is_default: true }));
  });

  it("says why a name was refused and keeps what was typed", async () => {
    vi.mocked(saveSavedFilter).mockRejectedValue(new Error('There is already a filter called "Rent only". Choose another name, or replace that one.'));
    render(<ListView listKey="balances" />);
    await open();
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save as new…" }));
    fireEvent.change(drawer().getByLabelText("Name for the new filter"), { target: { value: "Rent only" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save filter" }));
    expect((await drawer().findByText(/There is already a filter called/)).getAttribute("role")).toBe("alert");
    expect((drawer().getByLabelText("Name for the new filter") as HTMLInputElement).value).toBe("Rent only");
    expect((drawer().getByLabelText("Note") as HTMLInputElement).value).toBe("rent");
  });

  it("needs a name, and conditions that are complete, before it will save as new", async () => {
    render(<ListView listKey="balances" />);
    await open();
    expect((drawer().getByRole("button", { name: "Save as new…" }) as HTMLButtonElement).disabled).toBe(true);      // nothing to save
    addFilter("Note");
    expect((drawer().getByRole("button", { name: "Save as new…" }) as HTMLButtonElement).disabled).toBe(true);      // an empty box
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    fireEvent.click(drawer().getByRole("button", { name: "Save as new…" }));
    expect((drawer().getByRole("button", { name: "Save filter" }) as HTMLButtonElement).disabled).toBe(true);       // no name
  });

  it("renames the loaded filter", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    vi.mocked(changeSavedFilter).mockResolvedValue(set([filter(1, "Rent", { conditions: [NOTE] })]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    fireEvent.click(drawer().getByRole("button", { name: "Rename" }));
    fireEvent.change(drawer().getByLabelText("New name"), { target: { value: "Rent" } });
    fireEvent.click(drawer().getAllByRole("button", { name: "Rename" }).at(-1)!);
    await waitFor(() => expect(changeSavedFilter).toHaveBeenCalledWith("balances", 1, { name: "Rent" }));
  });

  it("deletes the loaded filter only after asking, and says what it means for a shared one", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([{ ...SHARED, can_edit: true }]));
    vi.mocked(deleteSavedFilter).mockResolvedValue(set([]));
    render(<ListView listKey="balances" config={{ isAdmin: true }} />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: /Recent/ }));
    fireEvent.click(drawer().getByRole("button", { name: "Delete" }));
    expect(screen.getByText(/removed for all of them/)).toBeTruthy();
    expect(deleteSavedFilter).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getAllByRole("dialog").at(-1)!).getByRole("button", { name: "Cancel" }));
    expect(deleteSavedFilter).not.toHaveBeenCalled();
    fireEvent.click(drawer().getByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getAllByRole("dialog").at(-1)!).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSavedFilter).toHaveBeenCalledWith("balances", 2));
    await waitFor(() => expect(drawer().getByRole("button", { name: /Choose/ })).toBeTruthy());     // nothing is loaded any more
    expect(drawer().getByLabelText("Date")).toBeTruthy();                                            // the draft is kept
  });

  it("keeps a shared filter read-only for someone who cannot change it, but lets them use it", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([SHARED]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: /Recent/ }));
    expect((drawer().getByLabelText("Date") as HTMLInputElement).value).toBe("2025-12-31");
    for (const name of ["Save", "Rename", "Delete"]) expect((drawer().getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
    expect(drawer().queryByRole("checkbox", { name: /default/i })).toBeNull();
    expect((drawer().getByRole("button", { name: "Save as new…" }) as HTMLButtonElement).disabled).toBe(false);       // a private copy is fine
  });

  it("marks and unmarks the person's own default", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    vi.mocked(changeSavedFilter).mockResolvedValue(set([{ ...MINE, is_default: true }], 1));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    fireEvent.click(drawer().getByRole("checkbox", { name: "My default" }));
    await waitFor(() => expect(changeSavedFilter).toHaveBeenCalledWith("balances", 1, { is_default: true }));
    await waitFor(() => expect((drawer().getByRole("checkbox", { name: "My default" }) as HTMLInputElement).checked).toBe(true));
  });

  it("drops the conditions a saved filter has that the list no longer offers, and says so", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([filter(5, "Old region check", {
      conditions: [AFTER, { field: "region", operator: "equals", value: "x" }], problems: [{ field: "region", reason: "region is not a column" }],
    })]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Old region check" }));
    expect(drawer().getByText(/1 condition was skipped: region is not offered by this list any more/)).toBeTruthy();
    expect(drawer().queryByText("not a column of this list")).toBeNull();
    expect(drawer().getByLabelText("Date")).toBeTruthy();
    expect((drawer().getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);        // unchanged apart from what was skipped
  });

  it("goes back to no saved filter without touching the draft", async () => {
    vi.mocked(fetchSavedFilters).mockResolvedValue(set([MINE]));
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Rent notes" }));
    fireEvent.click(drawer().getByRole("button", { name: /Rent notes/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "No saved filter" }));
    expect(drawer().getByRole("button", { name: /Choose/ })).toBeTruthy();
    expect((drawer().getByLabelText("Note") as HTMLInputElement).value).toBe("rent");
  });

  it("says when the saved filters could not be loaded, and still lets a filter be built and applied", async () => {
    vi.mocked(fetchSavedFilters).mockRejectedValue(new Error("The server answered 500"));
    render(<ListView listKey="balances" />);
    await open();
    expect((await drawer().findByText(/Could not load the saved filters/)).getAttribute("role")).toBe("alert");
    addFilter("Note");
    fireEvent.change(drawer().getByLabelText("Note"), { target: { value: "rent" } });
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [NOTE] }));
  });
});

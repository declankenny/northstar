// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FieldNode, FieldTree, ListColumn, ListPage, ListRequest, SavedFilter } from "./api";
import { ListView } from "./ListView";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn(), fetchListFields: vi.fn(), fetchListChoices: vi.fn(),
  fetchSavedFilters: vi.fn(),
}));

import { fetchList, fetchListChoices, fetchListFields, fetchSavedFilters } from "./api";

const COLUMNS: ListColumn[] = [{ key: "account", label: "Account", path_label: "Account", kind: "text", scale: null, linked: false }];
const LABELS: Record<string, string> = { is: "is", is_not: "is not", is_any_of: "is one of", is_not_any_of: "is not one of", is_empty: "is empty", is_not_empty: "is not empty" };
const SIX = Object.keys(LABELS).map((name) => ({ name, label: LABELS[name] }));
const field = (over: Partial<FieldNode>): FieldNode => ({ key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: [], choices: null, ...over });

const TREE: FieldTree = {
  fields: [],
  relations: [
    field({
      key: "account", label: "Account", path_label: "Account", kind: "choice", operators: SIX, choices: "records",
      children: { fields: [field({ key: "account.status", label: "Status", path_label: "Account › Status", kind: "choice", operators: SIX, choices: "values", values: ["Open", "Closed"] })], relations: [] },
    }),
  ],
};

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: [{ _id: 1, _links: {}, account: "Test account 1" }], total: 1, page: 1, pages: 1, page_size: 25, group: null,
  sort: { field: "account", direction: "asc" }, filters: [], skipped: [], default_filter_id: null, default_columns: ["account"], customised: false,
  skipped_columns: [], ...over,
});

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);
const open = async () => { fireEvent.click(await screen.findByRole("button", { name: /^Filters/ })); return screen.findByRole("dialog"); };
const drawer = () => within(screen.getByRole("dialog"));
const add = (path: string[]) => {
  fireEvent.click(drawer().getByRole("button", { name: "+ Add filter" }));
  const picker = within(drawer().getByLabelText("Columns to filter by"));
  if (path.length > 1) fireEvent.click(picker.getByRole("button", { name: `Show the columns of ${path[0]}` }));
  fireEvent.click(picker.getByRole("button", { name: path[path.length - 1] }));
};
const operator = (column: string, name: string) => fireEvent.change(drawer().getByLabelText(`How to compare ${column}`), { target: { value: name } });
const apply = () => fireEvent.click(drawer().getByRole("button", { name: "Apply changes" }));
const pick = (label: string, option: RegExp | string) => {
  fireEvent.focus(drawer().getByRole("combobox", { name: label }));
  fireEvent.mouseDown(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
};

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockImplementation(async (_key, request) => page({ filters: request.filters ?? [] }));      // the server answers with what was asked
  vi.mocked(fetchListFields).mockResolvedValue(TREE);
  vi.mocked(fetchListChoices).mockResolvedValue({ kind: "records", values: [], more: false, options: [{ id: 3, value: "Test dollars", detail: null }, { id: 4, value: "Test euros", detail: "EUR" }] });
  vi.mocked(fetchSavedFilters).mockResolvedValue({ filters: [], default_id: null });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the operators of a choice column in the drawer", () => {
  it("offers all six, in the order of the list, and starts a new filter at “is” with a type-ahead", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account", "Status"]);
    const select = drawer().getByLabelText("How to compare Account › Status") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["is", "is not", "is one of", "is not one of", "is empty", "is not empty"]);
    expect(select.value).toBe("is");
    expect(drawer().getByRole("combobox", { name: "Value for Account › Status" })).toBeTruthy();
    expect(drawer().queryByRole("checkbox")).toBeNull();
  });

  it("chooses one declared value with “is”, sends it as the value itself, and says it in a chip", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account", "Status"]);
    pick("Value for Account › Status", "Open");
    apply();
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, filters: [{ field: "account.status", operator: "is", value: "Open" }] }));
    expect(await screen.findByText("Account › Status is Open")).toBeTruthy();
  });

  it("chooses one record by typing part of its name or its detail, and sends its id", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account"]);
    await drawer().findByRole("combobox", { name: "Value for Account" });
    const box = drawer().getByRole("combobox", { name: "Value for Account" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "eur" } });
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(1);        // by the detail, EUR, as well as the name
    fireEvent.mouseDown(within(screen.getByRole("listbox")).getByRole("option", { name: /Test euros/ }));
    expect((box as HTMLInputElement).value).toBe("Test euros");
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account", operator: "is", value: 4 }]));
    expect(await screen.findByText("Account is Test euros")).toBeTruthy();
  });

  it("says “is not” the same way", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account"]);
    operator("Account", "is_not");
    await drawer().findByRole("combobox", { name: "Value for Account" });
    pick("Value for Account", /Test dollars/);
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account", operator: "is_not", value: 3 }]));
    expect(await screen.findByText("Account is not Test dollars")).toBeTruthy();
  });

  it("keeps the choice when the operator changes between one value and several, in both directions", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account"]);
    await drawer().findByRole("combobox", { name: "Value for Account" });
    pick("Value for Account", /Test euros/);
    operator("Account", "is_any_of");
    expect((await drawer().findByRole("checkbox", { name: /Test euros/ }) as HTMLInputElement).checked).toBe(true);
    expect((drawer().getByRole("checkbox", { name: "Test dollars" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(drawer().getByRole("checkbox", { name: "Test dollars" }));
    operator("Account", "is_not");
    expect((drawer().getByRole("combobox", { name: "Value for Account" }) as HTMLInputElement).value).toBe("Test euros");      // the first
  });

  it("takes several with “is not one of”, as check boxes, and sends the ids", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account"]);
    operator("Account", "is_not_any_of");
    fireEvent.click(await drawer().findByRole("checkbox", { name: /Test euros/ }));
    fireEvent.click(drawer().getByRole("checkbox", { name: "Test dollars" }));
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account", operator: "is_not_any_of", value: [4, 3] }]));
    expect(await screen.findByText("Account is not one of Test euros, Test dollars")).toBeTruthy();
  });

  it("takes no value for “is empty” and “is not empty”, and sends none", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account"]);
    await drawer().findByRole("combobox", { name: "Value for Account" });
    operator("Account", "is_empty");
    expect(drawer().queryByRole("combobox", { name: "Value for Account" })).toBeNull();
    expect(drawer().queryByRole("checkbox")).toBeNull();
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account", operator: "is_empty" }]));
    expect(await screen.findByText("Account is empty")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
    operator("Account", "is_not_empty");
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account", operator: "is_not_empty" }]));
  });

  it("will not apply “is” until one value is chosen, and says so", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account", "Status"]);
    expect(drawer().queryByText("Choose a value.")).toBeNull();                 // a new row is not nagged
    apply();
    expect(drawer().getByText("Choose a value.")).toBeTruthy();
    expect(requests()).toHaveLength(1);
    pick("Value for Account › Status", "Closed");
    expect(drawer().queryByText("Choose a value.")).toBeNull();
    apply();
    await waitFor(() => expect(requests().at(-1)?.filters).toEqual([{ field: "account.status", operator: "is", value: "Closed" }]));
  });

  it("closes the open list on Escape and leaves the drawer open, then closes the drawer on the next", async () => {
    render(<ListView listKey="balances" />);
    await open();
    add(["Account", "Status"]);
    fireEvent.focus(drawer().getByRole("combobox", { name: "Value for Account › Status" }));
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(drawer().getByRole("combobox", { name: "Value for Account › Status" }), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(drawer().getByRole("combobox", { name: "Value for Account › Status" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("loads a filter saved before the relabel, which stored the name is_any_of, as “is one of” with its choices ticked", async () => {
    const saved: SavedFilter = { id: 9, name: "Dollars", shared: false, is_default: false, can_edit: true, problems: [],
      conditions: [{ field: "account", operator: "is_any_of", value: [3] }] };
    vi.mocked(fetchSavedFilters).mockResolvedValue({ filters: [saved], default_id: null });
    render(<ListView listKey="balances" />);
    await open();
    fireEvent.click(await drawer().findByRole("button", { name: /Choose…/ }));
    fireEvent.click(drawer().getByRole("menuitem", { name: "Dollars" }));
    expect((drawer().getByLabelText("How to compare Account") as HTMLSelectElement).selectedOptions[0].textContent).toBe("is one of");
    expect((await drawer().findByRole("checkbox", { name: "Test dollars" }) as HTMLInputElement).checked).toBe(true);
  });
});

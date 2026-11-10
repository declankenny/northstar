// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountOptions, ListColumn, ListPage, ListRequest } from "./api";
import { AccountsList } from "./AccountsList";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchAccountOptions: vi.fn(), addAccount: vi.fn(), fetchList: vi.fn(), fetchListFields: vi.fn(),
}));

import { addAccount, fetchAccountOptions, fetchList, fetchListFields } from "./api";

const USD = { code: "USD", name: "US Dollar", minor_units: 2 };
const column = (key: string, label: string, kind: ListColumn["kind"] = "text"): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: key === "name", groupable: true });
const COLUMNS = [column("name", "Account"), column("type", "Type"), column("last_cents", "Last balance", "amount"), column("is_stale", "Stale", "yes_no")];

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, total: 1, page: 1, pages: 1, page_size: 25, group: null, sort: { field: "name", direction: "asc" },
  filters: [{ field: "is_open", operator: "is_yes", value: null }], skipped: [], default_filter_id: 1, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [],
  rows: [{ _id: 3, _links: { name: "/accounts/3" }, name: "Test checking", type: "Checking", last_cents: { value: 123456, scale: 2, unit: "USD" }, is_stale: 0 }], ...over,
});

const options = (over: Partial<AccountOptions> = {}): AccountOptions => ({
  currency: USD, currencies: [USD], today: "2026-11-10",
  classes: [{ id: 1, name: "Asset", types: [{ id: 1, name: "Checking" }] }, { id: 2, name: "Liability", types: [] }], ...over,
});

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);

beforeEach(() => {
  window.history.replaceState(null, "", "/accounts");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
  vi.mocked(fetchAccountOptions).mockResolvedValue(options());
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the Accounts page", () => {
  it("has a heading and the list called accounts, naming nothing else, so its own defaults and shared filter apply", async () => {
    render(<AccountsList isAdmin={false} />);
    expect(screen.getByRole("heading", { name: "Accounts" })).toBeTruthy();
    expect((await screen.findByRole("link", { name: "Test checking" })).getAttribute("href")).toBe("/accounts/3");
    expect(vi.mocked(fetchList).mock.calls[0][0]).toBe("accounts");
    expect(requests()[0]).toEqual({ page: 1 });
  });

  it("shows a stale flag as plain Yes or No and has no menu on a row", async () => {
    render(<AccountsList isAdmin />);
    const row = (await screen.findByText("Test checking")).closest("tr") as HTMLElement;
    expect(row.textContent).toContain("No");
    expect(screen.queryByRole("button", { name: /Actions for/ })).toBeNull();
  });

  it("says the system currency is not set, when it is not", async () => {
    vi.mocked(fetchAccountOptions).mockResolvedValue(options({ currency: null, currencies: [] }));
    render(<AccountsList isAdmin />);
    expect(await screen.findByText(/The system currency is not set yet/)).toBeTruthy();
  });

  it("says nothing about the currency when it is set", async () => {
    render(<AccountsList isAdmin />);
    await screen.findByText("Test checking");
    expect(screen.queryByText(/The system currency is not set yet/)).toBeNull();
  });

  it("has Add account, with Asset account and Liability account, once what it offers has loaded", async () => {
    render(<AccountsList isAdmin />);
    const button = screen.getByRole("button", { name: "Add account ▾" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    expect(screen.getByRole("menuitem", { name: "Asset account…" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Liability account…" })).toBeTruthy();
  });

  it("adds the account, closes the dialog and reads the list again in place with the same request, so the sort and filters stay", async () => {
    window.history.replaceState(null, "", "/accounts?sort=-last_cents&page=2");
    vi.mocked(addAccount).mockResolvedValue({ id: 9 });
    render(<AccountsList isAdmin />);
    await screen.findByText("Test checking");
    const before = requests().length;
    const button = screen.getByRole("button", { name: "Add account ▾" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("menuitem", { name: "Asset account…" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test savings" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await waitFor(() => expect(addAccount).toHaveBeenCalledTimes(1));
    expect(vi.mocked(addAccount).mock.calls[0][0]).toMatchObject({ account_class: "asset", name: "Test savings", type_id: 1 });
    await waitFor(() => expect(requests().length).toBe(before + 1));
    expect(requests()[before]).toEqual(requests()[before - 1]);
    expect(requests()[before]).toMatchObject({ page: 2 });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.location.search).toBe("?sort=-last_cents&page=2");           // the address is untouched
  });

  it("does not read the list again when the add is refused, and the dialog stays with what was typed", async () => {
    vi.mocked(addAccount).mockRejectedValue(new Error("An account named \"Test savings\" already exists."));
    render(<AccountsList isAdmin />);
    await screen.findByText("Test checking");
    const before = requests().length;
    const button = screen.getByRole("button", { name: "Add account ▾" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("menuitem", { name: "Asset account…" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test savings" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await screen.findByText(/already exists/)).toBeTruthy();
    expect(requests().length).toBe(before);
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Test savings");
  });
});

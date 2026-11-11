// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage as Account, ListColumn, ListPage, ListRequest } from "./api";
import { AccountPage } from "./AccountPage";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), fetchList: vi.fn(), fetchListFields: vi.fn(), addBalance: vi.fn(), exportList: vi.fn(),
}));
vi.mock("./NetWorthChart", () => ({ NetWorthChart: () => null }));

import { addBalance, exportList, fetchAccount, fetchList, fetchListFields, fetchNetWorth } from "./api";

const USD = { code: "USD", name: "US Dollar", minor_units: 2 };
const account = (over: Partial<Account> = {}): Account => ({
  id: 7, name: "Test savings", currency: USD, class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 30, earliest_date: "2024-01-01", last_date: "2026-06-01", last_cents: 100000, days_since: 10, stale: false,
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30", ...over,
});

const column = (key: string, label: string, kind: ListColumn["kind"]): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: key === "as_of_date", groupable: false });
const COLUMNS = [column("as_of_date", "Date", "date"), column("amount_cents", "Balance", "amount"), column("change_cents", "Change", "amount")];
const money = (value: number) => ({ value, scale: 2, unit: "USD" });
const row = (id: number, date: string, amount: number, change: number | null) => (
  { _id: id, _links: { as_of_date: `/balances/${id}` }, as_of_date: date, amount_cents: money(amount), change_cents: change === null ? null : money(change) });

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, total: 30, page: 1, pages: 3, page_size: 12, group: null, sort: { field: "as_of_date", direction: "desc" }, filters: [], skipped: [],
  default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [],
  rows: [row(30, "2026-06-01", 100000, 5000), row(29, "2026-05-01", 95000, -2500), row(1, "2024-01-01", 10000, null)], ...over,
});

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);
const body = () => screen.getByRole("table").querySelectorAll("tbody tr");
const nb = (text: string | null) => text?.replace(/ /g, " ");

beforeEach(() => {
  window.history.replaceState(null, "", "/accounts/7");
  vi.mocked(fetchAccount).mockResolvedValue(account());
  vi.mocked(fetchNetWorth).mockResolvedValue({ today: "2026-10-30", start: "2025-10-30", end: "2026-10-30", period: "month", series: [], limited: null, balance_count: 12 });
  vi.mocked(fetchList).mockResolvedValue(page());
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the balance history on the account page", () => {
  it("asks for the account's balances and nothing a person could change", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect(vi.mocked(fetchList).mock.calls[0][0]).toBe("account_balances");
    expect(requests()[0]).toEqual({ page: 1, params: { account: 7 } });
    expect(fetchListFields).not.toHaveBeenCalled();
  });

  it("has no search, Filters, Columns, group, export or rows per page, and no Edit or Delete", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect(screen.queryByRole("textbox", { name: "Search" })).toBeNull();
    for (const name of [/^Filters/, "Columns", /Edit balance/, /Delete balance/, /Column menu/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByText("Rows per page")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Export CSV" })).toHaveLength(1);     // only the account's own export, which an import reads back
  });

  it("shows the date, balance and change, the date opening the balance's page", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent?.replace(/[▲▼]/g, "").trim())).toEqual(["Date", "Balance", "Change"]);
    const cells = [...body()[0].querySelectorAll("td")];
    expect(cells.map((c) => nb(c.textContent))).toEqual(["Jun 1, 2026", "$1,000.00", "+$50.00"]);
    expect(within(cells[0] as HTMLElement).getByRole("link").getAttribute("href")).toBe("/balances/30");
  });

  it("writes the first balance's change as a dash, and a fall as a minus", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect([...body()].map((r) => nb(r.querySelectorAll("td")[2].textContent))).toEqual(["+$50.00", "-$25.00", "—"]);
  });

  it("colours a change by whether it helps: a liability that grows is bad", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ class_name: "Liability" }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    const tones = [...body()].map((r) => r.querySelectorAll("td")[2].querySelector("span")?.className);
    expect(tones).toEqual(["n", "p", "m"]);
  });

  it("keeps the sort and the page in the page and not in the address", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 2, params: { account: 7 } }));
    fireEvent.click(screen.getByRole("button", { name: /^Balance/ }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, sort: { field: "amount_cents", direction: "asc" }, params: { account: 7 } }));
    expect(window.location.search).toBe("");
  });

  it("says where it is, twelve to a page, and has no pager when there is one page", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    expect(screen.getByText("1–3 of 30")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    cleanup();
    vi.mocked(fetchList).mockResolvedValue(page({ total: 3, pages: 1 }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect(screen.queryByText(/Page 1 of/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  });

  it("reads the list again after a balance is added, keeping its sort", async () => {
    vi.mocked(addBalance).mockResolvedValue(account({ balance_count: 31 }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: /^Balance/ }));
    await waitFor(() => expect(requests().length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "Add balance" }));
    const dialog = await screen.findByRole("dialog", { name: "Add balance" });
    fireEvent.change(within(dialog).getByLabelText("Balance"), { target: { value: "1,100.00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(requests().length).toBe(3));
    expect(requests()[2]).toEqual({ page: 1, sort: { field: "amount_cents", direction: "asc" }, params: { account: 7 } });
  });

  it("counts the balances inside the chart's dates from the server's answer, and all of them from the account", async () => {
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    const tile = screen.getByText("Balances recorded").closest(".tile") as HTMLElement;
    await waitFor(() => expect(tile.querySelector(".val")!.textContent).toBe("12"));
    expect(tile.textContent).toContain("30 in all");
  });

  it("says there are no balances for an account with none, and asks for no list", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null }));
    render(<AccountPage id={7} isAdmin />);
    expect(await screen.findByText("No balances yet.")).toBeTruthy();
    expect(fetchList).not.toHaveBeenCalled();
  });

  it("lists a closed account's history and disables adding", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ is_open: false }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    expect((screen.getByRole("button", { name: "Add balance" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("This account is closed. Reopen it to add or change its balances.")).toBeTruthy();
  });

  it("starts another account on its first page", async () => {
    const { rerender } = render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(requests().at(-1)?.page).toBe(2));
    vi.mocked(fetchAccount).mockResolvedValue(account({ id: 8, name: "Test other" }));
    rerender(<AccountPage id={8} isAdmin />);
    await screen.findByRole("heading", { name: "Test other" });
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, params: { account: 8 } }));
    expect(exportList).not.toHaveBeenCalled();
  });

  it("says when the list could not be read, and tries again", async () => {
    vi.mocked(fetchList).mockRejectedValueOnce(new Error("The server is down.")).mockResolvedValue(page());
    render(<AccountPage id={7} isAdmin />);
    expect((await screen.findByRole("alert")).textContent).toContain("Could not load the list. The server is down.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
  });
});

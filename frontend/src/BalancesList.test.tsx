// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListColumn, ListPage } from "./api";
import { BalancesList } from "./BalancesList";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), fetchListFields: vi.fn(),
}));

import { fetchList, fetchListFields } from "./api";

const column = (key: string, label: string, kind: ListColumn["kind"] = "text"): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: false, groupable: true });
const related = (key: string, label: string, path: string): ListColumn => ({ ...column(key, label), path_label: path });      // as the server names a related column
const COLUMNS = [column("as_of_date", "Date", "date"), column("account", "Account"), related("account.type", "Type", "Account › Type"), column("amount_cents", "Value", "amount"),
  related("account.currency", "Currency", "Account › Currency"), column("reporting_value", "Reporting value", "amount"), column("note", "Note")];

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, total: 1, page: 1, pages: 1, page_size: 25, group: null, sort: { field: "as_of_date", direction: "desc" }, filters: [], skipped: [],
  default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [],
  rows: [{
    _id: 1, _links: { account: "/accounts/3" }, as_of_date: "2026-05-01", account: "Test dollars", "account.type": "Savings",
    amount_cents: { value: 12_000, scale: 2, unit: "USD" }, "account.currency": "USD", reporting_value: null, note: null,
  }], ...over,
});

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the Balances page", () => {
  it("has a heading and shows the balances list with the columns the server gives, a related one headed by where it comes from", async () => {
    render(<BalancesList isAdmin={false} />);
    expect(screen.getByRole("heading", { name: "Balances" })).toBeTruthy();
    expect(await screen.findByText("Test dollars")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent?.replace(/[▲▼▾]/g, "").trim())).toEqual(
      ["Date", "Account", "Account › Type", "Value", "Account › Currency", "Reporting value", "Note"]);
  });

  it("asks the server for the list called balances and names nothing else, so its own defaults apply", async () => {
    render(<BalancesList isAdmin={false} />);
    await screen.findByText("Test dollars");
    expect(vi.mocked(fetchList).mock.calls[0][0]).toBe("balances");
    expect(vi.mocked(fetchList).mock.calls[0][1]).toEqual({ page: 1 });
  });

  it("links the account to its page and writes a balance with no rate yet as a dash", async () => {
    render(<BalancesList isAdmin={false} />);
    expect((await screen.findByRole("link", { name: "Test dollars" })).getAttribute("href")).toBe("/accounts/3");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("says there are no balances yet, and where to add one, when there are none", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ total: 0, rows: [] }));
    render(<BalancesList isAdmin={false} />);
    expect(await screen.findByText("There are no balances yet. Add one from Update balances.")).toBeTruthy();
  });
});

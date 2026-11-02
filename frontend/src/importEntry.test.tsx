// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountList, AccountPage as Account, ListedAccount } from "./api";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchAccount: vi.fn(), fetchAccounts: vi.fn(), fetchNetWorth: vi.fn(), downloadExport: vi.fn() }));

import { downloadExport, fetchAccount, fetchAccounts } from "./api";

const page = (over: Partial<Account> = {}): Account => ({
  id: 7, name: "Demo Savings", class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null, stale: false, balances: [],
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30", ...over,
});

const listed = (id: number, name: string): ListedAccount => ({
  id, name, class_name: "Asset", type_name: "Savings", notes: null, balance_count: 0, last_date: null, last_cents: null, days_since: null, stale: false,
});

const list = (closed: boolean): AccountList => ({
  closed, accounts: [listed(7, "Demo Savings")], totals: closed ? null : { assets: 0, liabilities: 0 }, classes: [], today: "2026-10-30",
});

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("Import CSV on the account page", () => {
  it("is offered for an open account, and opens the import for that account", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(page());
    render(<AccountPage id={7} isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: "Import CSV…" }));
    expect(window.location.pathname).toBe("/accounts/7/import");
  });

  it("is not offered for a closed account", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(page({ is_open: false }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Demo Savings" });
    expect(screen.queryByRole("button", { name: "Import CSV…" })).toBeNull();
  });
});

describe("Import CSV on the accounts list", () => {
  it("is in the ⋯ menu of an open account, and opens the import for that account", async () => {
    vi.mocked(fetchAccounts).mockResolvedValue(list(false));
    render(<AccountsList isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Demo Savings" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Import CSV…" }));
    expect(window.location.pathname).toBe("/accounts/7/import");
  });

  it("is not in the menu of a closed account", async () => {
    vi.mocked(fetchAccounts).mockResolvedValue(list(false));
    render(<AccountsList isAdmin />);
    vi.mocked(fetchAccounts).mockResolvedValue(list(true));
    await screen.findByRole("button", { name: "Actions for Demo Savings" });
    fireEvent.click(screen.getByRole("button", { name: "Closed" }));
    await vi.waitFor(() => expect(fetchAccounts).toHaveBeenCalledWith(true, expect.anything()));
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Demo Savings" }));
    expect(await screen.findByRole("menuitem", { name: "Edit" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Import CSV…" })).toBeNull();
  });
});

describe("Export CSV", () => {
  it("is on the account page, for an open or a closed account, and downloads that account", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(page({ is_open: false }));
    render(<AccountPage id={7} isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Export CSV" }));
    expect(downloadExport).toHaveBeenCalledWith(7);
  });

  it("is in the menu of every account in the list, closed ones too, and downloads that account", async () => {
    vi.mocked(fetchAccounts).mockResolvedValue(list(true));
    render(<AccountsList isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Demo Savings" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Export CSV" }));
    expect(downloadExport).toHaveBeenCalledWith(7);
  });
});

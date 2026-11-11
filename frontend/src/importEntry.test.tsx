// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage as Account } from "./api";
import { AccountPage } from "./AccountPage";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), downloadExport: vi.fn() }));

import { downloadExport, fetchAccount } from "./api";

const page = (over: Partial<Account> = {}): Account => ({
  id: 7, name: "Demo Savings", currency: { code: "USD", name: "US Dollar", minor_units: 2 }, class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null, stale: false,
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30", ...over,
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

describe("Export CSV", () => {
  it("is on the account page, for an open or a closed account, and downloads that account", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(page({ is_open: false }));
    render(<AccountPage id={7} isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Export CSV" }));
    expect(downloadExport).toHaveBeenCalledWith(7);
  });
});

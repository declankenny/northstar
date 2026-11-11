// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage as Account } from "./api";
import { AccountPage } from "./AccountPage";
import { deferred } from "./testing";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchAccount: vi.fn(), fetchNetWorth: vi.fn() }));

import { fetchAccount } from "./api";

// An account with no balances, so the page asks for no chart and only the account matters here.
const account = (id: number, name: string): Account => ({
  id, name, currency: { code: "USD", name: "US Dollar", minor_units: 2 }, class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null, stale: false,
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30",
});

describe("AccountPage", () => {
  const asked = new Map<number, ReturnType<typeof deferred<Account>>>();

  beforeEach(() => {
    asked.clear();
    vi.mocked(fetchAccount).mockImplementation((id) => {
      const reply = deferred<Account>();
      asked.set(id, reply);
      return reply.promise;
    });
  });
  afterEach(cleanup);

  it("shows the account in the address, even when the answer for the one before arrives after it", async () => {
    const { rerender } = render(<AccountPage id={1} isAdmin />);
    rerender(<AccountPage id={2} isAdmin />);
    await act(async () => asked.get(2)!.resolve(account(2, "Second account")));
    expect(screen.getByRole("heading", { name: "Second account" })).toBeTruthy();

    await act(async () => asked.get(1)!.resolve(account(1, "First account")));
    expect(screen.getByRole("heading", { name: "Second account" })).toBeTruthy();
    expect(screen.queryByText("First account")).toBeNull();
  });

  it("does not show the error of an account that is no longer the one in the address", async () => {
    const { rerender } = render(<AccountPage id={1} isAdmin />);
    rerender(<AccountPage id={2} isAdmin />);
    await act(async () => asked.get(2)!.resolve(account(2, "Second account")));
    await act(async () => asked.get(1)!.reject(new Error("That account no longer exists.")));
    expect(screen.queryByText(/Could not load/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Second account" })).toBeTruthy();
  });
});

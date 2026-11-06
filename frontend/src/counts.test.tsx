// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AccountList, ListedAccount } from "./api";
import { AccountsList } from "./AccountsList";
import { conflictBanner } from "./conflicts";
import { type Locale, setLocale, US_ENGLISH } from "./locale";
import { setCurrency } from "./money";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchAccounts: vi.fn() }));

import { fetchAccounts } from "./api";

const GERMAN: Locale = { ...US_ENGLISH, tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".", date_template: "{day2}.{month2}.{year}", currency_position: "suffix" };

afterEach(() => {
  cleanup();
  setLocale(null);
  setCurrency(null);
  vi.resetAllMocks();
});

const account = (over: Partial<ListedAccount> = {}): ListedAccount => ({
  id: 7, name: "Test checking", currency: { code: "EUR", name: "Euro", minor_units: 2 }, class_name: "Asset", type_name: "Checking", notes: null, balance_count: 1234, last_date: "2026-10-31",
  last_cents: 123456, days_since: 1095, stale: true, ...over,
});

const list = (): AccountList => ({
  currency: { code: "EUR", name: "Euro", minor_units: 2 }, currencies: [{ code: "EUR", name: "Euro", minor_units: 2 }], closed: false, accounts: [account()], totals: { assets: 123456, liabilities: 0 },
  classes: [], today: "2026-11-05",
});

describe("counts follow the person's format", () => {
  it("groups the number of balances and the days since the last one in a list row", async () => {
    setLocale(GERMAN);
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    vi.mocked(fetchAccounts).mockResolvedValue(list());
    render(<AccountsList isAdmin />);
    const row = (await screen.findByText("Test checking")).closest("tr") as HTMLElement;
    const text = row.textContent ?? "";
    expect(text).toContain("1.234");
    expect(text).toContain("1.095 days ago");
    expect(text).toContain("31.10.2026");
  });

  it("writes them as before in US English", async () => {
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    vi.mocked(fetchAccounts).mockResolvedValue(list());
    render(<AccountsList isAdmin />);
    const text = ((await screen.findByText("Test checking")).closest("tr") as HTMLElement).textContent ?? "";
    expect(text).toContain("1,234");
    expect(text).toContain("1,095 days ago");
  });

  it("groups the number of balances in the conflict message", () => {
    setLocale(GERMAN);
    expect(conflictBanner(1234)).toContain("1.234 balances changed");
    expect(conflictBanner(2)).toContain("2 balances changed");
    expect(conflictBanner(1)).toContain("1 balance changed");
  });
});

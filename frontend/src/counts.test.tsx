// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ListColumn, ListPage } from "./api";
import { AccountsList } from "./AccountsList";
import { conflictBanner } from "./conflicts";
import { type Locale, setLocale, US_ENGLISH } from "./locale";
import { setCurrency } from "./money";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchAccountOptions: vi.fn(), fetchList: vi.fn(), fetchListFields: vi.fn() }));

import { fetchAccountOptions, fetchList, fetchListFields } from "./api";

const GERMAN: Locale = { ...US_ENGLISH, tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".", date_template: "{day2}.{month2}.{year}", currency_position: "suffix" };

afterEach(() => {
  cleanup();
  setLocale(null);
  setCurrency(null);
  vi.resetAllMocks();
});

const column = (key: string, label: string, kind: ListColumn["kind"] = "text"): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: false, groupable: true });
const COLUMNS = [column("name", "Account"), column("last_date", "Balance date", "date"), column("days_since", "Balance age (days)", "integer"), column("balance_count", "Balances", "integer")];

const show = () => {
  vi.mocked(fetchAccountOptions).mockResolvedValue({ currency: { code: "EUR", name: "Euro", minor_units: 2 }, currencies: [{ code: "EUR", name: "Euro", minor_units: 2 }], classes: [], today: "2026-11-05" });
  vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
  vi.mocked(fetchList).mockResolvedValue({
    columns: COLUMNS, total: 1, page: 1, pages: 1, page_size: 25, group: null, sort: { field: "name", direction: "asc" }, filters: [], skipped: [],
    default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [],
    rows: [{ _id: 7, _links: {}, name: "Test checking", last_date: "2026-10-31", days_since: 1095, balance_count: 1234 }],
  } as ListPage);
  render(<AccountsList isAdmin />);
};

describe("counts follow the person's format", () => {
  it("groups the number of balances and the days since the last one in a list row", async () => {
    setLocale(GERMAN);
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    show();
    const row = (await screen.findByText("Test checking")).closest("tr") as HTMLElement;
    const text = row.textContent ?? "";
    expect(text).toContain("1.234");
    expect(text).toContain("1.095");
    expect(text).toContain("31.10.2026");
  });

  it("writes them as before in US English", async () => {
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    show();
    const text = ((await screen.findByText("Test checking")).closest("tr") as HTMLElement).textContent ?? "";
    expect(text).toContain("1,234");
    expect(text).toContain("1,095");
  });

  it("groups the number of balances in the conflict message", () => {
    setLocale(GERMAN);
    expect(conflictBanner(1234)).toContain("1.234 balances changed");
    expect(conflictBanner(2)).toContain("2 balances changed");
    expect(conflictBanner(1)).toContain("1 balance changed");
  });
});

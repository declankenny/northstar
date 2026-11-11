// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListColumn, ListPage } from "./api";
import { Currencies } from "./Currencies";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchList: vi.fn(), fetchListFields: vi.fn() }));

import { fetchList, fetchListFields } from "./api";

const column = (key: string, label: string, kind: ListColumn["kind"] = "text"): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: key === "code", groupable: true });
const COLUMNS = [column("code", "Code"), column("name", "Name"), column("minor_units", "Decimal places", "integer"), column("is_enabled", "Enabled", "yes_no"), column("account_count", "Accounts", "integer")];

const row = (code: string, name: string, over: Record<string, unknown> = {}) => ({
  _id: code.charCodeAt(0), _links: { code: `/currencies/${code}` }, code, name, minor_units: 2, is_enabled: 0, account_count: 0, ...over,
});

const page = (rows: ReturnType<typeof row>[], over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows, total: rows.length, page: 1, pages: 1, page_size: 100, group: null, sort: { field: "code", direction: "asc" },
  filters: [], skipped: [], default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [], ...over,
});

beforeEach(() => {
  window.history.replaceState(null, "", "/currencies");
  vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
  vi.mocked(fetchList).mockResolvedValue(page([
    row("EUR", "Euro", { is_enabled: 1, account_count: 3 }), row("JPY", "Yen", { minor_units: 0 }),
    row("KWD", "Kuwaiti Dinar", { minor_units: 3, is_enabled: 1 }), row("USD", "US Dollar", { account_count: 9 }),
  ]));
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the Currencies page", () => {
  it("has the admin heading and a list called currencies, naming nothing else, so its own defaults apply", async () => {
    render(<Currencies />);
    expect(screen.getByRole("heading", { name: "Currencies" })).toBeTruthy();
    await screen.findByText("Euro");
    expect(vi.mocked(fetchList).mock.calls[0][0]).toBe("currencies");
    expect(vi.mocked(fetchList).mock.calls[0][1]).toEqual({ page: 1 });
  });

  it("lists each currency with its decimals, whether it is enabled and how many accounts use it", async () => {
    render(<Currencies />);
    await screen.findByText("Euro");
    const cells = (code: string) => [...within(screen.getByRole("table")).getAllByRole("row").find((r) => r.querySelector("td")?.textContent === code)!
      .querySelectorAll("td")].map((td) => td.textContent);
    expect(cells("EUR")).toEqual(["EUR", "Euro", "2", "Yes", "3"]);
    expect(cells("JPY")).toEqual(["JPY", "Yen", "0", "No", "0"]);
    expect(cells("KWD")).toEqual(["KWD", "Kuwaiti Dinar", "3", "Yes", "0"]);
    expect(cells("USD")).toEqual(["USD", "US Dollar", "2", "No", "9"]);
  });

  it("links each currency's code to its page, and a row has no action of its own", async () => {
    render(<Currencies />);
    expect((await screen.findByRole("link", { name: "EUR" })).getAttribute("href")).toBe("/currencies/EUR");
    expect(screen.getByRole("link", { name: "KWD" }).getAttribute("href")).toBe("/currencies/KWD");
    expect(screen.queryByRole("button", { name: /Actions for/ })).toBeNull();
  });

  it("says nothing about a system currency", async () => {
    render(<Currencies />);
    await screen.findByText("Euro");
    expect(screen.queryByText(/system currency/i)).toBeNull();
  });

  it("shows the reason when the list cannot be loaded", async () => {
    vi.mocked(fetchList).mockRejectedValue(new Error("The server answered 500"));
    render(<Currencies />);
    expect(await screen.findByText(/The server answered 500/)).toBeTruthy();
  });
});

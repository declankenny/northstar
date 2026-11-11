// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AccountOptions, AccountPage as Account, ListColumn, ListPage, UpdatePage } from "./api";
import { AddAccountDialog } from "./AccountDialogs";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";
import { type Locale, setLocale, US_ENGLISH } from "./locale";
import { type Currency, setCurrency } from "./money";
import { UpdateBalances } from "./UpdateBalances";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchAccountOptions: vi.fn(), fetchList: vi.fn(), fetchListFields: vi.fn(), fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), fetchUpdate: vi.fn(),
}));

import { fetchAccount, fetchAccountOptions, fetchList, fetchListFields, fetchNetWorth, fetchUpdate } from "./api";

const USD: Currency = { code: "USD", name: "US Dollar", minor_units: 2 };
const EUR: Currency = { code: "EUR", name: "Euro", minor_units: 2 };
const JPY: Currency = { code: "JPY", name: "Yen", minor_units: 0 };
const GERMAN: Locale = { ...US_ENGLISH, tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".",
  date_template: "{day2}.{month2}.{year}", currency_position: "suffix", currency_code_spacing: " " };

afterEach(() => {
  cleanup();
  setLocale(null);
  setCurrency(null);
  vi.resetAllMocks();
});

const list = (currencies: Currency[]): AccountOptions => ({
  currency: currencies[0], currencies, today: "2026-06-03",
  classes: [{ id: 1, name: "Asset", types: [{ id: 1, name: "Savings" }] }, { id: 2, name: "Liability", types: [] }],
});

describe("the Add account dialog with several currencies", () => {
  const open = (l: AccountOptions, isAdmin = true) => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AddAccountDialog options={l} isAdmin={isAdmin} accountClass="asset" onSave={onSave} onClose={vi.fn()} />);
    return onSave;
  };

  it("offers a Currency box only when more than the system currency can be used, system currency first", () => {
    open(list([USD, EUR, JPY]));
    const box = screen.getByLabelText("Currency") as HTMLSelectElement;
    expect([...box.options].map((o) => o.textContent)).toEqual(["USD · US Dollar (system currency)", "EUR · Euro", "JPY · Yen"]);
    expect(box.value).toBe("USD");
    cleanup();
    open(list([USD]));
    expect(screen.queryByLabelText("Currency")).toBeNull();
  });

  it("reads the balance in the chosen currency: its placeholder, its reading line and its hint, and clears what was typed", () => {
    open(list([USD, EUR, JPY]));
    const amount = screen.getByLabelText(/Current balance/) as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "25.5" } });
    expect(screen.getByText("Reads as $25.50")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "JPY" } });
    expect(amount.value).toBe("");
    expect(amount.placeholder).toBe("0");
    expect(screen.getByText(/Amounts are in Yen \(JPY\)\./)).toBeTruthy();
    fireEvent.change(amount, { target: { value: "1234" } });
    expect(screen.getByText(/^Reads as JPY\s1,234$/)).toBeTruthy();
    fireEvent.change(amount, { target: { value: "12.5" } });
    expect(screen.getByText(/no decimal places/)).toBeTruthy();
  });

  it("sends the chosen currency with the account, and sends none when there is only one", async () => {
    const onSave = open(list([USD, EUR]));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test euros" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "EUR" } });
    fireEvent.change(screen.getByLabelText(/Current balance/), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({ name: "Test euros", amount: "100", currency: "EUR" });
    cleanup();
    const single = open(list([USD]));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await waitFor(() => expect(single).toHaveBeenCalledTimes(1));
    expect("currency" in single.mock.calls[0][0]).toBe(false);
  });

  it("points an admin, and only an admin, to the Currencies page for another currency", () => {
    open(list([USD, EUR]), true);
    expect(screen.getByRole("link", { name: /Need another currency/ }).getAttribute("href")).toBe("/currencies");
    cleanup();
    open(list([USD, EUR]), false);
    expect(screen.queryByRole("link", { name: /Need another currency/ })).toBeNull();
  });
});

describe("the Accounts list with accounts in several currencies", () => {
  const column = (key: string, label: string, kind: ListColumn["kind"] = "text"): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: false, groupable: true });
  const COLUMNS = [column("name", "Account"), column("type", "Type"), column("currency", "Currency"), column("last_cents", "Last balance", "amount"), column("last_date", "Balance date", "date")];
  const listed = (id: number, name: string, code: string, value: number, scale: number) => ({
    _id: id, _links: {}, name, type: "Savings", currency: code, last_cents: { value, scale, unit: code }, last_date: "2026-05-12",
  });
  const show = (rows: ListPage["rows"]) => {
    vi.mocked(fetchAccountOptions).mockResolvedValue(list([USD, EUR, JPY]));
    vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
    vi.mocked(fetchList).mockResolvedValue({
      columns: COLUMNS, rows, total: rows.length, page: 1, pages: 1, page_size: 25, group: null, sort: { field: "name", direction: "asc" }, filters: [],
      skipped: [], default_filter_id: null, default_columns: COLUMNS.map((c) => c.key), customised: false, skipped_columns: [],
    });
    render(<AccountsList isAdmin />);
  };

  it("has a Currency column, and writes each balance in its own account's currency", async () => {
    show([listed(1, "Test checking", "USD", 150000, 2), listed(2, "Test euros", "EUR", 1000000, 2), listed(3, "Test yen", "JPY", 250000, 0)]);
    await screen.findByText("Test euros");
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent?.replace(/[▲▼▾]/g, "").trim())).toContain("Currency");
    const cells = (name: string) => [...(screen.getByText(name).closest("tr") as HTMLElement).querySelectorAll("td")].map((c) => c.textContent?.replace(/ /g, " "));
    expect(cells("Test checking").slice(1, 4)).toEqual(["Savings", "USD", "$1,500.00"]);
    expect(cells("Test euros").slice(1, 4)).toEqual(["Savings", "EUR", "EUR 10,000.00"]);
    expect(cells("Test yen").slice(1, 4)).toEqual(["Savings", "JPY", "JPY 250,000"]);
  });

  it("writes them in the person's format", async () => {
    setLocale(GERMAN);
    show([listed(2, "Test euros", "EUR", 1000000, 2)]);
    const row = (await screen.findByText("Test euros")).closest("tr") as HTMLElement;
    expect(row.textContent?.replace(/ /g, " ")).toContain("10.000,00 EUR");
    expect(row.textContent).toContain("12.05.2026");
  });
});

describe("an account page for an account in another currency", () => {
  const euros = (): Account => ({
    id: 7, name: "Test euros", currency: EUR, class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null,
    stale_after_days: 35, balance_count: 2, earliest_date: "2026-04-30", last_date: "2026-05-12", last_cents: 1000000, days_since: 22,
    stale: false, today: "2026-06-03", types: [], other_class: { id: 2, name: "Liability", types: [] },
  });

  it("has a Currency tile and writes every amount in the account's currency", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(euros());
    vi.mocked(fetchNetWorth).mockResolvedValue({
      today: "2026-06-03", start: "2026-04-30", end: "2026-06-03", period: "month", limited: null, balance_count: 2,
      series: [{ date: "2026-04-30", assets: 940000, liabilities: 0, net_worth: 940000 }, { date: "2026-05-12", assets: 1000000, liabilities: 0, net_worth: 1000000 }],
    });
    const col = (key: string, label: string, kind: ListColumn["kind"]): ListColumn => ({ key, label, path_label: label, kind, scale: null, linked: false, groupable: false });
    vi.mocked(fetchList).mockResolvedValue({
      columns: [col("as_of_date", "Date", "date"), col("amount_cents", "Balance", "amount"), col("change_cents", "Change", "amount")],
      rows: [{ _id: 2, _links: { as_of_date: "/balances/2" }, as_of_date: "2026-05-12", amount_cents: { value: 1000000, scale: 2, unit: "EUR" }, change_cents: { value: 60000, scale: 2, unit: "EUR" } },
             { _id: 1, _links: { as_of_date: "/balances/1" }, as_of_date: "2026-04-30", amount_cents: { value: 940000, scale: 2, unit: "EUR" }, change_cents: null }],
      total: 2, page: 1, pages: 1, page_size: 12, group: null, sort: { field: "as_of_date", direction: "desc" }, filters: [], skipped: [], default_filter_id: null,
      default_columns: ["as_of_date", "amount_cents", "change_cents"], customised: false, skipped_columns: [],
    });
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Test euros" });
    const tile = screen.getByText("Currency").closest(".tile") as HTMLElement;
    expect(within(tile).getByText("EUR")).toBeTruthy();
    expect(within(tile).getByText("Euro")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Test euros" }).textContent).not.toContain("EUR");        // the header does not name it
    const latest = screen.getByText("Latest balance").closest(".tile") as HTMLElement;
    expect(latest.textContent).toContain("EUR 10,000.00");
    const table = await screen.findByRole("table");
    const cells = (n: number) => [...table.querySelectorAll("tbody tr")].map((r) => r.querySelectorAll("td")[n].textContent);
    expect(cells(1)).toEqual(["EUR 10,000.00", "EUR 9,400.00"]);
    expect(cells(2)).toEqual(["+EUR 600.00", "—"]);                    // the change is in the account's own currency too
  });
});

describe("the Update balances screen with accounts in several currencies", () => {
  const row = (id: number, name: string, currency: Currency, last: number) => ({
    id, name, currency, class_name: "Asset", type_name: "Savings", stale_after_days: 35, last_date: "2026-05-12", last_cents: last,
    days_since: 22, stale: false, existing_cents: null, existing_version: null,
  });
  const open = async () => {
    vi.mocked(fetchUpdate).mockResolvedValue({
      date: "2026-06-03", today: "2026-06-03", saved: null,
      rows: [row(1, "Test checking", USD, 150000), row(2, "Test euros", EUR, 1000000), row(3, "Test yen", JPY, 250000)],
    } as UpdatePage);
    render(<UpdateBalances />);
    await screen.findByLabelText("New balance for Test yen");
  };

  it("has a Currency column and writes each last balance in its own currency", async () => {
    await open();
    const cells = (name: string) => [...(screen.getByText(name).closest("tr") as HTMLElement).querySelectorAll("td")].map((c) => c.textContent);
    expect(cells("Test checking")[1]).toBe("USD");
    expect(cells("Test euros")[1]).toBe("EUR");
    expect(cells("Test yen")[1]).toBe("JPY");
    expect(cells("Test yen")[2]).toContain("JPY 250,000");
    expect(cells("Test euros")[2]).toContain("EUR 10,000.00");
  });

  it("marks each box and reads each amount with its own currency, and yen takes no decimals", async () => {
    await open();
    expect([...document.querySelectorAll(".ub-in i")].map((i) => i.textContent)).toEqual(["$", "EUR", "JPY"]);
    fireEvent.change(screen.getByLabelText("New balance for Test yen"), { target: { value: "251,000" } });
    fireEvent.change(screen.getByLabelText("New balance for Test euros"), { target: { value: "10,150.5" } });
    const reads = () => [...document.querySelectorAll(".reads")].map((e) => e.textContent);
    expect(reads()).toContain("Reads as JPY 251,000");
    expect(reads()).toContain("Reads as EUR 10,150.50");
    fireEvent.change(screen.getByLabelText("New balance for Test yen"), { target: { value: "251,000.5" } });
    await act(async () => {});
    expect(reads().join(" ")).toContain("no decimal places");
  });
});

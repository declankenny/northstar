// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type AccountList, type PropertyList, type PropertyRow } from "./api";
import { AddAccountDialog } from "./AccountDialogs";
import { amountPlaceholder, centsToInput, formatCents, parseCents, setCurrency } from "./money";
import { SystemProperties } from "./SystemProperties";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchProperties: vi.fn(), saveProperty: vi.fn() }));

import { fetchProperties, saveProperty } from "./api";

const USD = { code: "USD", name: "US Dollar", minor_units: 2 };
const JPY = { code: "JPY", name: "Yen", minor_units: 0 };
const KWD = { code: "KWD", name: "Kuwaiti Dinar", minor_units: 3 };

afterEach(() => {
  cleanup();
  setCurrency(null);
  vi.resetAllMocks();
});

describe("amounts in the currency's minor unit", () => {
  it("shows dollars as before and every other currency with its code and a no-break space", () => {
    expect(formatCents(123456)).toBe("$1,234.56");
    setCurrency(JPY);
    expect(formatCents(1234567)).toBe("JPY 1,234,567");
    expect(formatCents(-5)).toBe("-JPY 5");
    setCurrency(KWD);
    expect(formatCents(1234)).toBe("KWD 1.234");
    expect(formatCents(-1)).toBe("-KWD 0.001");
    expect(formatCents(0)).toBe("KWD 0.000");
  });

  it("reads typed text with the currency's digits and refuses more", () => {
    setCurrency(JPY);
    expect(parseCents("1,234")).toBe(1234);
    expect(parseCents("12.5")).toBeNull();
    expect(parseCents("12.")).toBeNull();
    expect(parseCents("$12")).toBeNull();
    setCurrency(KWD);
    expect(parseCents("1.234")).toBe(1234);
    expect(parseCents("1.2")).toBe(1200);
    expect(parseCents("1.2345")).toBeNull();
    setCurrency(USD);
    expect(parseCents("-$25.50")).toBe(-2550);
    expect(parseCents("1.234")).toBeNull();
  });

  it("starts an amount box and its placeholder with the same number of digits", () => {
    expect(amountPlaceholder()).toBe("0.00");
    expect(centsToInput(123456)).toBe("1234.56");
    setCurrency(JPY);
    expect(amountPlaceholder()).toBe("0");
    expect(centsToInput(-1234)).toBe("-1234");
    setCurrency(KWD);
    expect(amountPlaceholder()).toBe("0.000");
    expect(centsToInput(1234)).toBe("1.234");
  });

  it("keeps the ceiling of the server in every currency", () => {
    setCurrency(JPY);
    expect(parseCents("9999999999999")).toBe(99_999_999_999_99);
    expect(parseCents("10000000000000")).toBeNull();
  });
});

const accountList = (currency: AccountList["currency"]): AccountList => ({
  currency, currencies: currency ? [currency] : [], closed: false, accounts: [], totals: { assets: 0, liabilities: 0 }, today: "2026-11-04",
  classes: [{ id: 1, name: "Asset", types: [{ id: 1, name: "Savings" }] }, { id: 2, name: "Liability", types: [] }],
});

describe("the Add account dialog", () => {
  const open = (list: AccountList, isAdmin: boolean) =>
    render(<AddAccountDialog list={list} isAdmin={isAdmin} accountClass="asset" onSave={vi.fn()} onClose={vi.fn()} />);

  it("has no currency field with one currency, and says which one amounts are in", () => {
    open(accountList(USD), true);
    expect(screen.queryByLabelText(/currency/i)).toBeNull();
    expect(screen.getByText(/Amounts are in US Dollar \(USD\)\./)).toBeTruthy();
    expect((screen.getByLabelText(/Current balance/) as HTMLInputElement).placeholder).toBe("0.00");
  });

  it("follows the system currency's digits", () => {
    setCurrency(JPY);
    open(accountList(JPY), true);
    expect((screen.getByLabelText(/Current balance/) as HTMLInputElement).placeholder).toBe("0");
    expect(screen.getByText(/Amounts are in Yen \(JPY\)\./)).toBeTruthy();
  });

  it("warns instead of showing the form while the system currency is unset, and sends an admin to System properties", () => {
    open(accountList(null), true);
    expect(screen.getByRole("alert").textContent).toContain("Choose the system currency first");
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(screen.getByRole("link", { name: "Open System properties" }).getAttribute("href")).toBe("/system-properties");
  });

  it("tells someone who is not an admin to ask one, with no link", () => {
    open(accountList(null), false);
    expect(screen.getByText("Ask an admin to set the system currency.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open System properties" })).toBeNull();
  });
});

describe("the system currency on the System properties page", () => {
  const property = (over: Partial<PropertyRow>): PropertyRow => ({
    name: "system.currency", type: "String", value: null, allow_null: false, hint: "A hint.", read_only: false, options: [], ...over,
  });
  const page = (over: Partial<PropertyRow> = {}): PropertyList => ({
    properties: [property(over)], currencies: [{ ...USD, name: "US Dollar" }, JPY, KWD], locales: [],
  });

  it("is a search box over the catalog, one option per currency with its code and name", async () => {
    vi.mocked(fetchProperties).mockResolvedValue(page());
    const { container } = render(<SystemProperties />);
    const box = await screen.findByLabelText("system.currency");
    expect(box.getAttribute("list")).toBe("sp-currencies");
    expect(box.getAttribute("spellcheck")).toBe("false");        // a code is not prose, so no red squiggle
    const options = [...container.querySelectorAll("datalist#sp-currencies option")];
    expect(options.map((o) => [o.getAttribute("value"), o.textContent])).toEqual([["USD", "US Dollar"], ["JPY", "Yen"], ["KWD", "Kuwaiti Dinar"]]);
  });

  it("saves the code that was typed or chosen, and tells the app the currency changed", async () => {
    vi.mocked(fetchProperties).mockResolvedValue(page());
    vi.mocked(saveProperty).mockResolvedValue(page({ value: "JPY", read_only: true }));
    const changed = vi.fn();
    render(<SystemProperties onCurrencyChange={changed} />);
    fireEvent.change(await screen.findByLabelText("system.currency"), { target: { value: "JPY" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(saveProperty).toHaveBeenCalledWith("system.currency", "JPY");
    expect(changed).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("system.currency") as HTMLInputElement).disabled).toBe(true);
    expect(within(screen.getByRole("tabpanel")).getByText("Locked")).toBeTruthy();
  });

  it("is locked once set, so it cannot be searched or edited", async () => {
    vi.mocked(fetchProperties).mockResolvedValue(page({ value: "USD", read_only: true }));
    render(<SystemProperties />);
    const box = (await screen.findByLabelText("system.currency")) as HTMLInputElement;
    expect([box.value, box.disabled]).toEqual(["USD", true]);
  });

  it("shows the refusal beside the box when the code is not in the catalog", async () => {
    const { RequestError } = await import("./api");
    vi.mocked(fetchProperties).mockResolvedValue(page());
    vi.mocked(saveProperty).mockRejectedValue(new RequestError("That isn't a currency in the catalog.", {}, 422, [], null, []));
    render(<SystemProperties />);
    fireEvent.change(await screen.findByLabelText("system.currency"), { target: { value: "ZZZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That isn't a currency in the catalog.");
  });
});

describe("the default number and date format on the System properties page", () => {
  const property = (over: Partial<PropertyRow> = {}): PropertyRow => ({
    name: "ui.locale.default", type: "String", value: "en-US", allow_null: false, hint: "A hint.", read_only: false, options: [], ...over,
  });
  const page = (over: Partial<PropertyRow> = {}): PropertyList => ({
    properties: [property(over)], currencies: [],
    locales: [{ tag: "de-DE", label: "German (Germany)" }, { tag: "en-US", label: "English (United States)" }],
  });

  it("is a dropdown of the supported formats by name, set to the stored one, with nothing to type", async () => {
    vi.mocked(fetchProperties).mockResolvedValue(page());
    const { container } = render(<SystemProperties />);
    const box = (await screen.findByLabelText("ui.locale.default")) as HTMLSelectElement;
    expect(box.tagName).toBe("SELECT");
    expect([...box.options].map((o) => [o.value, o.textContent])).toEqual([
      ["de-DE", "German (Germany)"], ["en-US", "English (United States)"]]);
    expect(box.value).toBe("en-US");
    expect(container.querySelector("datalist#sp-locales")).toBeNull();
  });

  it("saves the format that was chosen and stays editable", async () => {
    vi.mocked(fetchProperties).mockResolvedValue(page());
    vi.mocked(saveProperty).mockResolvedValue(page({ value: "de-DE" }));
    render(<SystemProperties />);
    const box = await screen.findByLabelText("ui.locale.default");
    fireEvent.change(box, { target: { value: "de-DE" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(saveProperty).toHaveBeenLastCalledWith("ui.locale.default", "de-DE");
    expect((screen.getByLabelText("ui.locale.default") as HTMLSelectElement).disabled).toBe(false);
  });

  it("shows a refusal from the server beside the dropdown", async () => {
    const { RequestError } = await import("./api");
    vi.mocked(fetchProperties).mockResolvedValue(page());
    vi.mocked(saveProperty).mockRejectedValue(new RequestError("That isn't a supported number and date format.", {}, 422, [], null, []));
    render(<SystemProperties />);
    fireEvent.change(await screen.findByLabelText("ui.locale.default"), { target: { value: "de-DE" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That isn't a supported number and date format.");
  });
});

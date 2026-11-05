// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type CurrencyRow } from "./api";
import { Currencies, matches } from "./Currencies";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchCurrencies: vi.fn() }));

import { fetchCurrencies } from "./api";

const row = (code: string, name: string, over: Partial<CurrencyRow> = {}): CurrencyRow => ({
  code, name, minor_units: 2, is_enabled: false, account_count: 0, ...over,
});

const catalog = [
  row("EUR", "Euro", { is_enabled: true, account_count: 3 }),
  row("JPY", "Yen", { minor_units: 0 }),
  row("KWD", "Kuwaiti Dinar", { minor_units: 3, is_enabled: true }),
  row("USD", "US Dollar", { account_count: 9 }),
];

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const open = async () => {
  vi.mocked(fetchCurrencies).mockResolvedValue({ currencies: catalog });
  render(<Currencies />);
  await screen.findByText("Euro");
};
const codes = () => within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);

describe("matching", () => {
  it("takes a code that starts with the text, or a name that contains it, ignoring case", () => {
    const usd = row("USD", "US Dollar");
    expect(matches(usd, "")).toBe(true);
    expect(matches(usd, "  ")).toBe(true);
    expect(matches(usd, "us")).toBe(true);
    expect(matches(usd, "usd")).toBe(true);
    expect(matches(usd, "dol")).toBe(true);
    expect(matches(usd, "sd")).toBe(false);       // inside a code does not count, so "sd" does not find USD
    expect(matches(usd, "euro")).toBe(false);
  });
});

describe("the Currencies page", () => {
  it("lists each currency with its decimals, whether it is enabled and how many accounts use it", async () => {
    await open();
    const cells = (code: string) => [...within(screen.getByRole("table")).getAllByRole("row").find((r) => r.querySelector("td")?.textContent === code)!
      .querySelectorAll("td")].map((td) => td.textContent);
    expect(cells("EUR")).toEqual(["EUR", "Euro", "2", "Yes", "3"]);
    expect(cells("JPY")).toEqual(["JPY", "Yen", "0", "No", "0"]);
    expect(cells("KWD")).toEqual(["KWD", "Kuwaiti Dinar", "3", "Yes", "0"]);
    expect(cells("USD")).toEqual(["USD", "US Dollar", "2", "No", "9"]);
    expect(screen.getByText("4 of 4 shown")).toBeTruthy();
  });

  it("shows the stored flag and says nothing about a system currency", async () => {
    await open();
    expect(screen.queryByText(/system currency/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /system/i })).toBeNull();
  });

  it("searches by code or name as you type", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Search currencies"), { target: { value: "dinar" } });
    expect(codes()).toEqual(["KWD"]);
    fireEvent.change(screen.getByLabelText("Search currencies"), { target: { value: "e" } });
    expect(codes()).toEqual(["EUR", "JPY"]);          // EUR starts with it, and "Yen" contains it; Kuwaiti Dinar and US Dollar have no e
  });

  it("filters to the currencies in use, and to the enabled ones", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "In use" }));
    expect(codes()).toEqual(["EUR", "USD"]);
    fireEvent.click(screen.getByRole("button", { name: "Enabled" }));
    expect(codes()).toEqual(["EUR", "KWD"]);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(codes()).toHaveLength(4);
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("combines the search and the filter, and says when nothing matches", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Enabled" }));
    fireEvent.change(screen.getByLabelText("Search currencies"), { target: { value: "usd" } });
    expect(screen.getByText("No currency matches.")).toBeTruthy();
    expect(screen.getByText("0 of 4 shown")).toBeTruthy();
  });

  it("shows the reason when the list cannot be loaded", async () => {
    vi.mocked(fetchCurrencies).mockRejectedValue(new Error("The server answered 500"));
    render(<Currencies />);
    expect((await screen.findByRole("alert")).textContent).toBe("The server answered 500");
  });
});

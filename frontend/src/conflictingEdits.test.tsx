// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Conflict, RequestError, type UpdatePage, type UpdateRow } from "./api";
import { UpdateBalances } from "./UpdateBalances";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchUpdate: vi.fn(), saveUpdate: vi.fn(),
}));

import { fetchUpdate, saveUpdate } from "./api";

const conflict = (over: Partial<Conflict> = {}): Conflict => ({
  kind: "changed", account_id: 7, account_name: "Demo Savings", currency: { code: "USD", name: "US Dollar", minor_units: 2 }, date: "2026-03-31", balance_id: 11, version: 9,
  amount_cents: 120000, note: "Sam's correction", by: "Sam Example", on: "2026-11-02", ...over,
});

const refusal = (...conflicts: Conflict[]) => new RequestError("That balance changed since you opened it. Nothing was saved.", {}, 409, [], null, conflicts);

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  Element.prototype.scrollIntoView = vi.fn();      // jsdom has none, and the Update screen scrolls to the first marked row
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

// -- the Update screen --

const row = (id: number, name: string, over: Partial<UpdateRow> = {}): UpdateRow => ({
  id, name, currency: { code: "USD", name: "US Dollar", minor_units: 2 }, class_name: "Asset", type_name: "Savings", stale_after_days: 30, last_date: "2026-02-28", last_cents: 90000, days_since: 20,
  stale: false, existing_cents: null, existing_version: null, ...over,
});

const updatePage = (rows: UpdateRow[]): UpdatePage => ({ date: "2026-03-31", today: "2026-10-30", saved: null, rows });

describe("saving on the Update balances screen", () => {
  const box = (name: string) => screen.getByRole("textbox", { name: `New balance for ${name}` }) as HTMLInputElement;
  const loadedRows = () => updatePage([
    row(1, "Demo Savings", { existing_cents: 100000, existing_version: 5 }), row(2, "Demo Brokerage"), row(3, "Demo Checking"),
  ]);

  it("sends the version each changed row loaded, and none for a date that had no balance", async () => {
    vi.mocked(fetchUpdate).mockResolvedValue(loadedRows());
    vi.mocked(saveUpdate).mockResolvedValue({ ...loadedRows(), saved: { added: 1, updated: 1, unchanged: 0 } });
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Demo Savings" });
    fireEvent.change(box("Demo Savings"), { target: { value: "1050.00" } });
    fireEvent.change(box("Demo Brokerage"), { target: { value: "5100.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    await vi.waitFor(() => expect(saveUpdate).toHaveBeenCalledWith("2026-03-31", { 1: "1050.00", 2: "5100.00" }, { 1: 5, 2: null }));
  });

  it("refuses all of it, marks the rows that moved on, keeps what was typed, and shows the balances as they now are", async () => {
    vi.mocked(fetchUpdate).mockResolvedValueOnce(loadedRows()).mockResolvedValue(updatePage([
      row(1, "Demo Savings", { existing_cents: 120000, existing_version: 9 }),
      row(2, "Demo Brokerage", { existing_cents: 500000, existing_version: 10 }), row(3, "Demo Checking")]));
    vi.mocked(saveUpdate).mockRejectedValue(new RequestError("2 balances changed since you opened this date. Nothing was saved.", {}, 409, [], null, [
      conflict({ account_id: 1 }), conflict({ kind: "added", account_id: 2, account_name: "Demo Brokerage", amount_cents: 500000, version: 10 })]));
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Demo Savings" });
    fireEvent.change(box("Demo Savings"), { target: { value: "1050.00" } });
    fireEvent.change(box("Demo Brokerage"), { target: { value: "5100.00" } });
    fireEvent.change(box("Demo Checking"), { target: { value: "2400.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));

    const banner = await screen.findByText(/^Nothing was saved\. 2 balances changed since you opened this date/);
    expect(banner.textContent).toContain("pressing Save again replaces them with what you typed.");
    expect(await screen.findByText("Changed by Sam Example on Nov 2, 2026: now $1,200.00")).toBeTruthy();
    expect(screen.getByText("Added by Sam Example on Nov 2, 2026: now $5,000.00")).toBeTruthy();
    expect([box("Demo Savings").value, box("Demo Brokerage").value, box("Demo Checking").value]).toEqual(["1050.00", "5100.00", "2400.00"]);
    expect(fetchUpdate).toHaveBeenCalledTimes(2);                      // the date was read again
  });

  it("saves the typed amounts when Save is pressed again, with the versions of the balances as they now are", async () => {
    vi.mocked(fetchUpdate).mockResolvedValueOnce(loadedRows()).mockResolvedValue(updatePage([
      row(1, "Demo Savings", { existing_cents: 120000, existing_version: 9 }), row(2, "Demo Brokerage"), row(3, "Demo Checking")]));
    vi.mocked(saveUpdate).mockRejectedValueOnce(refusal(conflict({ account_id: 1 })))
      .mockResolvedValue({ ...loadedRows(), saved: { added: 0, updated: 1, unchanged: 0 } });
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Demo Savings" });
    fireEvent.change(box("Demo Savings"), { target: { value: "1050.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    await screen.findByText("Changed by Sam Example on Nov 2, 2026: now $1,200.00");
    await vi.waitFor(() => expect((screen.getByRole("button", { name: "Save balances" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    await vi.waitFor(() => expect(saveUpdate).toHaveBeenLastCalledWith("2026-03-31", { 1: "1050.00" }, { 1: 9 }));
  });

  it("still shows a refusal about an amount the old way", async () => {
    vi.mocked(fetchUpdate).mockResolvedValue(loadedRows());
    vi.mocked(saveUpdate).mockRejectedValue(new RequestError("Some amounts need fixing. Nothing was saved.", { 2: "Enter an amount like 1234.56 or -25.00." }, 422));
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Demo Savings" });
    fireEvent.change(box("Demo Brokerage"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    expect(await screen.findByText("Enter an amount like 1234.56 or -25.00.")).toBeTruthy();
    expect(fetchUpdate).toHaveBeenCalledTimes(1);
  });
});

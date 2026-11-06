// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type AccountPage as Account, type Conflict, RequestError, type UpdatePage, type UpdateRow } from "./api";
import { AccountPage } from "./AccountPage";
import { UpdateBalances } from "./UpdateBalances";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), editBalance: vi.fn(), deleteBalance: vi.fn(), fetchUpdate: vi.fn(), saveUpdate: vi.fn(),
}));
vi.mock("./NetWorthChart", () => ({ NetWorthChart: () => null }));

import { deleteBalance, editBalance, fetchAccount, fetchNetWorth, fetchUpdate, saveUpdate } from "./api";

const conflict = (over: Partial<Conflict> = {}): Conflict => ({
  kind: "changed", account_id: 7, account_name: "Demo Savings", date: "2026-03-31", balance_id: 11, version: 9,
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

// -- the account page: edit and delete --

const account = (): Account => ({
  id: 7, name: "Demo Savings", class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 2, earliest_date: "2026-02-28", last_date: "2026-03-31", last_cents: 100000, days_since: 10, stale: false,
  balances: [
    { id: 11, as_of_date: "2026-03-31", amount_cents: 100000, note: null, version: 5 },
    { id: 10, as_of_date: "2026-02-28", amount_cents: 90000, note: null, version: 3 },
  ],
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30",
});

describe("editing a balance that changed since it was opened", () => {
  beforeEach(() => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    vi.mocked(fetchNetWorth).mockResolvedValue({ today: "2026-10-30", start: "2026-02-28", end: "2026-10-30", period: "month", series: [], limited: null });
  });

  async function openEdit() {
    render(<AccountPage id={7} isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit balance of Mar 31, 2026" }));
    return screen.getByRole("dialog", { name: "Edit balance" });
  }

  it("sends the version it loaded", async () => {
    vi.mocked(editBalance).mockResolvedValue(account());
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText("Balance"), { target: { value: "1,050.00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(editBalance).toHaveBeenCalledWith(11, { date: "2026-03-31", amount: "1,050.00", note: "" }, 5));
  });

  it("says what happened, keeps what was typed, and offers Close or the current value", async () => {
    vi.mocked(editBalance).mockRejectedValue(refusal(conflict()));
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText("Balance"), { target: { value: "1,050.00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    const notice = await within(dialog).findByRole("alert");
    expect(notice.textContent).toBe(
      "Nothing was saved. Demo Savings on Mar 31, 2026 was changed by Sam Example on Nov 2, 2026. It is now $1,200.00 (you opened it at $1,000.00).");
    expect((within(dialog).getByLabelText("Balance") as HTMLInputElement).value).toBe("1,050.00");
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Use the current value" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("shows the balance as it now is on the page behind the dialog, which stays open", async () => {
    const changed = account();
    changed.balances[0] = { ...changed.balances[0], amount_cents: 120000, version: 9 };
    vi.mocked(fetchAccount).mockResolvedValueOnce(account()).mockResolvedValue(changed);
    vi.mocked(editBalance).mockRejectedValue(refusal(conflict()));
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await within(dialog).findByRole("alert");
    await vi.waitFor(() => expect(fetchAccount).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(screen.getAllByText("$1,200.00").length).toBeGreaterThan(0));
    expect(screen.getByRole("dialog", { name: "Edit balance" })).toBeTruthy();
  });

  it("fills in the current value, says whose it is, and the next save sends the current version", async () => {
    vi.mocked(editBalance).mockRejectedValueOnce(refusal(conflict())).mockResolvedValue(account());
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText("Balance"), { target: { value: "1,050.00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Use the current value" }));
    const now = screen.getByRole("dialog", { name: "Edit balance" });
    expect((within(now).getByLabelText("Balance") as HTMLInputElement).value).toBe("1200.00");
    expect((within(now).getByLabelText("Note (optional)") as HTMLInputElement).value).toBe("Sam's correction");
    expect(within(now).queryByRole("alert")).toBeNull();
    expect(within(now).getByRole("status").textContent).toBe("Showing the current value, changed by Sam Example on Nov 2, 2026. Your typed values were dropped.");
    fireEvent.change(within(now).getByLabelText("Balance"), { target: { value: "1250.00" } });
    fireEvent.click(within(now).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(editBalance).toHaveBeenLastCalledWith(11, { date: "2026-03-31", amount: "1250.00", note: "Sam's correction" }, 9));
  });

  it("says a deleted balance was deleted, and only offers Close", async () => {
    vi.mocked(editBalance).mockRejectedValue(refusal(conflict({ kind: "deleted", amount_cents: null, note: null, version: null })));
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    const notice = await screen.findByRole("alert");
    expect(notice.textContent).toBe("Nothing was saved. The balance for Demo Savings on Mar 31, 2026 was deleted by Sam Example on Nov 2, 2026.");
    expect(screen.getAllByRole("button", { name: /Close|Use the current value|Save/ }).map((b) => b.textContent)).toEqual(["Close"]);
  });

  it("shows any other refusal as before", async () => {
    vi.mocked(editBalance).mockRejectedValue(new RequestError("Enter an amount like 1234.56 or -25.00.", {}, 422));
    const dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Enter an amount like 1234.56 or -25.00.");
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeTruthy();
  });
});

describe("deleting a balance that changed since it was opened", () => {
  beforeEach(() => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    vi.mocked(fetchNetWorth).mockResolvedValue({ today: "2026-10-30", start: "2026-02-28", end: "2026-10-30", period: "month", series: [], limited: null });
  });

  async function openDelete() {
    render(<AccountPage id={7} isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete balance of Mar 31, 2026" }));
    return screen.getByRole("dialog", { name: "Delete this balance?" });
  }

  it("sends the version it loaded", async () => {
    vi.mocked(deleteBalance).mockResolvedValue(account());
    const dialog = await openDelete();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await vi.waitFor(() => expect(deleteBalance).toHaveBeenCalledWith(11, 5));
  });

  it("says nothing was deleted and why, offers only Close, and refreshes the page behind", async () => {
    vi.mocked(deleteBalance).mockRejectedValue(refusal(conflict()));
    const dialog = await openDelete();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    const notice = await within(dialog).findByRole("alert");
    expect(notice.textContent).toBe(
      "Nothing was deleted. Demo Savings on Mar 31, 2026 was changed by Sam Example on Nov 2, 2026. It is now $1,200.00 (you opened it at $1,000.00).");
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual(["Close"]);
    await vi.waitFor(() => expect(fetchAccount).toHaveBeenCalledTimes(2));
  });
});

// -- the Update screen --

const row = (id: number, name: string, over: Partial<UpdateRow> = {}): UpdateRow => ({
  id, name, class_name: "Asset", type_name: "Savings", stale_after_days: 30, last_date: "2026-02-28", last_cents: 90000, days_since: 20,
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

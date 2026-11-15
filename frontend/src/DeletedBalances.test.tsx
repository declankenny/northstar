// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type DeletedBalance, type DeletedBalances as Data, RequestError } from "./api";
import { DeletedBalances } from "./DeletedBalances";
import { clearFlash, peekFlash } from "./flash";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchDeletedBalances: vi.fn(), restoreDeletedBalance: vi.fn() }));

import { fetchDeletedBalances, restoreDeletedBalance } from "./api";

const USD = { code: "USD", name: "US Dollar", minor_units: 2 };
const entry = (over: Partial<DeletedBalance> = {}): DeletedBalance => ({
  id: 5, entry_id: 41, account_id: 1, account_name: "Joint savings", account_open: true, currency: USD, as_of_date: "2026-01-31", amount_cents: 1245000, note: "Statement total",
  deleted_by: "Sam", deleted_on: "2026-11-12", purge_on: "2027-02-10", ...over,
});
const data = (balances: DeletedBalance[], over: Partial<Data> = {}): Data => ({ cleanup_on: true, retention_days: 90, balances, ...over });

beforeEach(() => window.history.replaceState(null, "", "/deleted-balances"));
afterEach(() => {
  cleanup();
  clearFlash();
  vi.resetAllMocks();
});

const open = async () => fireEvent.click((await screen.findAllByRole("button", { name: "Restore balance…" }))[0]);

describe("the Deleted balances page", () => {
  it("lists each balance with its account, date, amount, who deleted it, when and when it goes for good", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry()]));
    render(<DeletedBalances />);
    const row = (await screen.findByText("Joint savings", { selector: "td" })).closest("tr") as HTMLElement;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent))
      .toEqual(["Joint savings", "Jan 31, 2026", "$12,450.00", "Sam", "Nov 12, 2026", "Feb 10, 2027", "Restore balance…"]);
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent))
      .toEqual(["Account", "Balance date", "Amount", "Deleted by", "Deleted", "Permanently deleted on", ""]);
  });

  it("marks a closed account, and says nothing is scheduled, and why, when the cleanup is off", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry({ account_open: false, purge_on: null })], { cleanup_on: false }));
    render(<DeletedBalances />);
    const row = (await screen.findByText("Not scheduled")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Closed")).toBeTruthy();
    expect(screen.getByText(/switched off, so deleted balances are kept/)).toBeTruthy();
  });

  it("says so when nothing is deleted", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([]));
    render(<DeletedBalances />);
    expect(await screen.findByText(/No deleted balances/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByLabelText("Account")).toBeNull();
  });

  it("filters by account, offering only accounts that have something deleted", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([
      entry({ id: 1, account_id: 1, account_name: "Joint savings" }), entry({ id: 2, account_id: 2, account_name: "Car loan", amount_cents: -820000 }),
      entry({ id: 3, account_id: 1, account_name: "Joint savings", as_of_date: "2026-02-28" }),
    ]));
    render(<DeletedBalances />);
    const select = (await screen.findByLabelText("Account")) as HTMLSelectElement;
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["All accounts", "Car loan", "Joint savings"]);
    expect(screen.getAllByRole("row")).toHaveLength(4);
    fireEvent.change(select, { target: { value: "2" } });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("-$8,200.00")).toBeTruthy();
    fireEvent.change(select, { target: { value: "" } });
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("confirms with the amount and note, restores, leaves a notice and opens the balance", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry()]));
    vi.mocked(restoreDeletedBalance).mockResolvedValue({ id: 5, account_id: 1, as_of_date: "2026-01-31" });
    render(<DeletedBalances />);
    await open();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("$12,450.00")).toBeTruthy();
    expect(within(dialog).getByText(/Statement total/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore balance" }));
    await waitFor(() => expect(window.location.pathname).toBe("/balances/5"));
    expect(restoreDeletedBalance).toHaveBeenCalledWith(5, 41);       // the deletion that was shown
    expect(peekFlash()).toBe("The balance for Jan 31, 2026 was restored.");
  });

  it("a date that has a balance now is refused with a link to that balance, and only Close is offered", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry()]));
    const refused = new RequestError("Joint savings already has a balance for that date. Restoring would replace it, so change or delete it first, then try again.",
      {}, 409, [], null, [], null, { balance_id: 9, amount_cents: 1200000 });
    vi.mocked(restoreDeletedBalance).mockRejectedValue(refused);
    render(<DeletedBalances />);
    await open();
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Restore balance" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Nothing was restored.");
    expect(alert.textContent).toContain("$12,000.00");
    expect(within(alert).getByRole("link", { name: "See that balance" }).getAttribute("href")).toBe("/balances/9");
    expect(screen.queryByRole("button", { name: "Restore balance" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
    expect(window.location.pathname).toBe("/deleted-balances");
    expect(peekFlash()).toBeNull();
    expect(vi.mocked(fetchDeletedBalances).mock.calls.length).toBeGreaterThan(1);      // read again
  });

  it("a balance that was changed since it was shown is refused in words, with Close only, and the list is read again", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry()]));
    vi.mocked(restoreDeletedBalance).mockRejectedValue(new RequestError("This balance was changed by someone else since you opened it. Nothing was restored.", {}, 409));
    render(<DeletedBalances />);
    await open();
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Restore balance" }));
    expect((await screen.findByRole("alert")).textContent).toContain("changed by someone else");
    expect(screen.queryByRole("button", { name: "Restore balance" })).toBeNull();
    expect(vi.mocked(fetchDeletedBalances).mock.calls.length).toBeGreaterThan(1);
  });

  it("a closed account is refused in words, with Close only", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry({ account_open: false })]));
    vi.mocked(restoreDeletedBalance).mockRejectedValue(new RequestError("Joint savings is closed. Reopen it before changing its balances.", {}, 422));
    render(<DeletedBalances />);
    await open();
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Restore balance" }));
    expect((await screen.findByRole("alert")).textContent).toContain("is closed");
    expect(screen.queryByRole("link", { name: "See that balance" })).toBeNull();
  });

  it("a failure that is not a refusal keeps the dialog open to try again", async () => {
    vi.mocked(fetchDeletedBalances).mockResolvedValue(data([entry()]));
    vi.mocked(restoreDeletedBalance).mockRejectedValue(new Error("The server answered 500"));
    render(<DeletedBalances />);
    await open();
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Restore balance" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The server answered 500");
    expect(screen.getByRole("button", { name: "Restore balance" })).toBeTruthy();
  });
});

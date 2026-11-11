// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type AccountPage, type BalancePageData, type Conflict, RequestError } from "./api";
import { BalancePage } from "./BalancePage";
import { navigate } from "./router";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchBalance: vi.fn(), fetchNeighbours: vi.fn(), editBalance: vi.fn(), deleteBalance: vi.fn(),
}));
vi.mock("./router", async (original) => ({ ...(await original<typeof import("./router")>()), goBack: vi.fn() }));

import { deleteBalance, editBalance, fetchBalance, fetchNeighbours } from "./api";
import { goBack } from "./router";

const EUR = { code: "EUR", name: "Euro", minor_units: 2 };
const account = (over: Partial<AccountPage> = {}): AccountPage => ({
  id: 3, name: "Test euros", currency: EUR, class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 3, earliest_date: "2026-02-01", last_date: "2026-04-20", last_cents: 30000, days_since: 10, stale: false,
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-06-03", ...over,
});
const page = (over: Partial<BalancePageData> = {}): BalancePageData => ({
  account: account(), balance: { id: 12, as_of_date: "2026-04-20", amount_cents: 30000, note: "Statement balance", version: 7 },
  reporting: { value: 33000, scale: 2, unit: "USD", rate_date: "2026-03-01" },
  entered_by: "Sample Admin", entered_on: "2026-04-22", changed_by: "Sample Admin", changed_on: "2026-04-22", ...over,
});
const conflict = (over: Partial<Conflict> = {}): Conflict => ({
  kind: "changed", account_id: 3, account_name: "Test euros", currency: EUR, date: "2026-04-20", balance_id: 12, version: 9,
  amount_cents: 31000, note: "Declan's correction", by: "Declan", on: "2026-11-10", ...over,
});
const refusal = (...conflicts: Conflict[]) => new RequestError("That balance changed since you opened it. Nothing was saved.", {}, 409, [], null, conflicts);

const amountBox = () => screen.getByLabelText("Balance in EUR") as HTMLInputElement;
const noteBox = () => screen.getByLabelText("Note (optional)") as HTMLInputElement;
const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
const shown = async () => { render(<BalancePage id={12} />); return screen.findByRole("heading", { name: "Test euros" }); };

beforeEach(() => {
  window.history.replaceState(null, "", "/balances/12");
  vi.mocked(fetchBalance).mockResolvedValue(page());
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

describe("the balance page", () => {
  it("names the balance in the breadcrumb, puts the account in the title and the date under it, and shows the balance", async () => {
    await shown();
    expect(document.querySelector(".crumb")?.textContent).toBe("Balances / Test euros · Apr 20, 2026");
    expect(screen.getByRole("link", { name: "Test euros" }).getAttribute("href")).toBe("/accounts/3");
    expect(screen.getByText("Savings · Asset")).toBeTruthy();
    expect(document.querySelector(".sub")?.textContent).toBe("Apr 20, 2026");
    expect(amountBox().value).toBe("300.00");
    expect(noteBox().value).toBe("Statement balance");
    expect(screen.queryByLabelText("Date")).toBeNull();                         // the date is the balance's name, not a field
    expect(button("Save").disabled).toBe(true);                                 // nothing to save yet
  });

  it("shows the details beside it: the currency, the value in the system currency with the date of its rate, and who entered and changed it", async () => {
    await shown();
    const details = within(document.querySelector(".facts-list") as HTMLElement);
    expect(details.getByText("EUR")).toBeTruthy();
    expect(details.getByText("Value in USD")).toBeTruthy();
    expect(details.getByText("$330.00 (at the rate of Mar 1, 2026)")).toBeTruthy();
    expect(details.getAllByText("by Sample Admin, Apr 22, 2026")).toHaveLength(2);
    expect(screen.queryByText(/neighbour|previous balance|next balance/i)).toBeNull();
  });

  it("says there is no rate rather than showing a value, and shows no conversion for an account in the system currency", async () => {
    vi.mocked(fetchBalance).mockResolvedValue(page({ reporting: { value: null, scale: 2, unit: "USD", rate_date: null } }));
    await shown();
    expect(screen.getByText("No EUR rate on or before this date")).toBeTruthy();
    cleanup();
    vi.mocked(fetchBalance).mockResolvedValue(page({ reporting: null }));
    await shown();
    expect(screen.queryByText(/Value in/)).toBeNull();
  });

  it("says a balance that is gone no longer exists, and any other failure as it is", async () => {
    vi.mocked(fetchBalance).mockRejectedValue(new RequestError("That balance no longer exists.", {}, 404));
    render(<BalancePage id={12} />);
    expect(await screen.findByText(/That balance no longer exists\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to Balances" }).getAttribute("href")).toBe("/balances");
    cleanup();
    vi.mocked(fetchBalance).mockRejectedValue(new Error("The server is not answering."));
    render(<BalancePage id={12} />);
    expect(await screen.findByText(/Could not load this balance\. The server is not answering\./)).toBeTruthy();
  });

  it("keeps the line that says how the amount was read beside its label, so no line is reserved between the amount and the note", async () => {
    await shown();
    const row = document.querySelector(".label-row") as HTMLElement;
    expect(within(row).getByText("Balance in EUR")).toBeTruthy();
    expect(row.querySelector(".reads")).not.toBeNull();                                   // there, and empty, beside the label
    expect(document.querySelector(".reads")?.textContent).toBe("");
    expect(document.querySelectorAll(".panel .field + .reads, .panel label .reads")).toHaveLength(0);   // not under the box, and not inside a label
    expect((screen.getByLabelText("Balance in EUR") as HTMLInputElement).value).toBe("300.00");        // the box is still the label's
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    expect((await within(row).findByText("Reads as EUR 325.50"))).toBeTruthy();           // and says it there
  });

  it("turns Save on when the amount or the note changes, and says how a changed amount was read, not before", async () => {
    await shown();
    expect(screen.queryByText(/Reads as/)).toBeNull();
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    expect(await screen.findByText("Reads as EUR 325.50")).toBeTruthy();
    expect(button("Save").disabled).toBe(false);
    fireEvent.change(amountBox(), { target: { value: "300.00" } });
    expect(button("Save").disabled).toBe(true);                                 // back to what it was
    fireEvent.change(noteBox(), { target: { value: "corrected" } });
    expect(button("Save").disabled).toBe(false);
  });
});

describe("saving", () => {
  it("sends the amount and note with the version and the unchanged date, takes the balance as the server now has it, and says Saved for a moment", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(editBalance).mockResolvedValue(account());
    await shown();
    vi.mocked(fetchBalance).mockResolvedValue(page({ balance: { id: 12, as_of_date: "2026-04-20", amount_cents: 32550, note: "corrected", version: 8 },
      reporting: { value: 35805, scale: 2, unit: "USD", rate_date: "2026-03-01" }, changed_by: "Declan", changed_on: "2026-11-10" }));
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    fireEvent.change(noteBox(), { target: { value: "corrected" } });
    fireEvent.click(button("Save"));
    await waitFor(() => expect(editBalance).toHaveBeenCalledWith(12, { date: "2026-04-20", amount: "325.5", note: "corrected" }, 7));
    await waitFor(() => expect(screen.getByRole("status", { name: "" }).textContent === "" || screen.getByText("Saved")).toBeTruthy());
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(amountBox().value).toBe("325.50");                                    // as the server holds it
    expect(button("Save").disabled).toBe(true);
    expect(screen.getByText("$358.05 (at the rate of Mar 1, 2026)")).toBeTruthy();
    expect(screen.getByText("by Declan, Nov 10, 2026")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(3100); });
    expect(screen.queryByText("Saved")).toBeNull();                              // and then it goes
  });

  it("sends the next save with the new version", async () => {
    vi.mocked(editBalance).mockResolvedValue(account());
    await shown();
    vi.mocked(fetchBalance).mockResolvedValue(page({ balance: { id: 12, as_of_date: "2026-04-20", amount_cents: 31000, note: "Statement balance", version: 8 } }));
    fireEvent.change(amountBox(), { target: { value: "310" } });
    fireEvent.click(button("Save"));
    await screen.findByText("Saved");
    fireEvent.change(amountBox(), { target: { value: "320" } });
    fireEvent.click(button("Save"));
    await waitFor(() => expect(editBalance).toHaveBeenLastCalledWith(12, { date: "2026-04-20", amount: "320", note: "Statement balance" }, 8));
  });

  it("shows a refusal as the server words it and keeps what was typed", async () => {
    vi.mocked(editBalance).mockRejectedValue(new RequestError("Enter an amount like 1234.56 or -25.00.", {}, 422));
    await shown();
    fireEvent.change(amountBox(), { target: { value: "abc" } });
    fireEvent.click(button("Save"));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter an amount like 1234.56 or -25.00.");
    expect(amountBox().value).toBe("abc");
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("says who changed the balance meanwhile, saves nothing, and offers the current value", async () => {
    vi.mocked(editBalance).mockRejectedValue(refusal(conflict()));
    await shown();
    // The details are asked for again behind the message; the version to send is the one the person was shown as current, whenever that answer lands.
    vi.mocked(fetchBalance).mockResolvedValue(page({ balance: { id: 12, as_of_date: "2026-04-20", amount_cents: 31000, note: "Declan's correction", version: 7 }, changed_by: "Declan", changed_on: "2026-11-10" }));
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    fireEvent.click(button("Save"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent?.replace(/ /g, " ")).toBe("Nothing was saved. Test euros on Apr 20, 2026 was changed by Declan on Nov 10, 2026. It is now EUR 310.00 (you opened it at EUR 300.00).");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();           // Save is replaced by the way forward
    await waitFor(() => expect(screen.getByText("by Declan, Nov 10, 2026")).toBeTruthy());     // the details show who changed it
    fireEvent.click(button("Use the current value"));
    expect(amountBox().value).toBe("310.00");
    expect(noteBox().value).toBe("Declan's correction");
    expect(screen.getByText(/Showing the current value, changed by Declan on Nov 10, 2026\. Your typed values were dropped\./)).toBeTruthy();
    expect(button("Save").disabled).toBe(true);
    vi.mocked(editBalance).mockResolvedValue(account());
    fireEvent.change(amountBox(), { target: { value: "315" } });
    fireEvent.click(button("Save"));
    await waitFor(() => expect(editBalance).toHaveBeenLastCalledWith(12, { date: "2026-04-20", amount: "315", note: "Declan's correction" }, 9));
  });

  it("says a balance deleted meanwhile was deleted, and offers no way to save it", async () => {
    vi.mocked(editBalance).mockRejectedValue(refusal(conflict({ kind: "deleted", amount_cents: null, note: null, version: null })));
    await shown();
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    fireEvent.click(button("Save"));
    expect((await screen.findByRole("alert")).textContent).toContain("was deleted by Declan on Nov 10, 2026.");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Use the current value" })).toBeNull();
    expect(amountBox().disabled).toBe(true);
    expect(button("Delete…").disabled).toBe(true);
  });
});

describe("a closed account", () => {
  it("says so, and changes nothing: the fields, Save and Delete are off, and Cancel is Back", async () => {
    vi.mocked(fetchBalance).mockResolvedValue(page({ account: account({ is_open: false }) }));
    await shown();
    expect(screen.getByText("This account is closed. Reopen it to change its balances.")).toBeTruthy();
    expect(screen.getByText("Closed")).toBeTruthy();
    expect(amountBox().disabled).toBe(true);
    expect(noteBox().disabled).toBe(true);
    expect(button("Save").disabled).toBe(true);
    expect(button("Delete…").disabled).toBe(true);
    expect(button("Back")).toBeTruthy();
  });
});

describe("deleting", () => {
  const older = { as_of_date: "2026-03-01", amount_cents: 25000 };
  const newer = { as_of_date: "2026-05-02", amount_cents: 41000 };
  const text = async () => (await screen.findByRole("dialog")).querySelector(".sub")!.textContent?.replace(/ /g, " ");

  it("asks first, with what happens to the history, and says it was deleted", async () => {
    vi.mocked(deleteBalance).mockResolvedValue(account());
    vi.mocked(fetchNeighbours).mockResolvedValue({ older, newer: null });
    await shown();
    fireEvent.click(button("Delete…"));
    const dialog = await screen.findByRole("dialog");
    expect(fetchNeighbours).toHaveBeenCalledWith(12);
    expect(within(dialog).getByText("Delete this balance?")).toBeTruthy();
    expect(within(dialog).getByText("The EUR 300.00 entry for Apr 20, 2026 is removed. Until the next entry, the balance will go back to EUR 250.00 (entered Mar 1, 2026).")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteBalance).toHaveBeenCalledWith(12, 7));
    expect((await screen.findByText(/The balance was deleted\./)).textContent).toContain("Back to Balances");
    expect(screen.queryByLabelText("Balance in EUR")).toBeNull();
  });

  it("says the balance before it comes back, or where the history starts, or that there is none", async () => {
    await shown();
    vi.mocked(fetchNeighbours).mockResolvedValue({ older, newer });
    fireEvent.click(button("Delete…"));
    expect(await text()).toBe("The EUR 300.00 entry for Apr 20, 2026 is removed. Until the next entry, the balance will go back to EUR 250.00 (entered Mar 1, 2026).");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    vi.mocked(fetchNeighbours).mockResolvedValue({ older: null, newer });
    fireEvent.click(button("Delete…"));
    await waitFor(() => expect(fetchNeighbours).toHaveBeenCalledTimes(2));
    expect(await text()).toBe("The EUR 300.00 entry for Apr 20, 2026 is removed. It is the first balance, so the history will start at the next entry, on May 2, 2026.");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    vi.mocked(fetchNeighbours).mockResolvedValue({ older: null, newer: null });
    fireEvent.click(button("Delete…"));
    await waitFor(() => expect(fetchNeighbours).toHaveBeenCalledTimes(3));
    expect(await text()).toBe("The EUR 300.00 entry for Apr 20, 2026 is removed. It is the only balance, so this account will have no history.");
  });

  it("asks nothing of the server until Delete… is pressed, and shows a refusal beside the form without a dialog", async () => {
    vi.mocked(fetchNeighbours).mockRejectedValue(new RequestError("That balance no longer exists.", {}, 404));
    await shown();
    expect(fetchNeighbours).not.toHaveBeenCalled();
    fireEvent.click(button("Delete…"));
    expect((await screen.findByRole("alert")).textContent).toBe("That balance no longer exists.");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says nothing was deleted when someone changed the balance first, and keeps the page", async () => {
    vi.mocked(fetchNeighbours).mockResolvedValue({ older, newer: null });
    vi.mocked(deleteBalance).mockRejectedValue(refusal(conflict()));
    await shown();
    fireEvent.click(button("Delete…"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/Nothing was deleted\./)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Test euros" })).toBeTruthy();
  });

  it("does not delete when Cancel is pressed", async () => {
    vi.mocked(fetchNeighbours).mockResolvedValue({ older, newer: null });
    await shown();
    fireEvent.click(button("Delete…"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deleteBalance).not.toHaveBeenCalled();
  });
});

describe("leaving", () => {
  it("goes back to where the person came from, or to the list", async () => {
    await shown();
    fireEvent.click(button("Cancel"));
    expect(goBack).toHaveBeenCalledWith("/balances");
  });

  it("asks before leaving with unsaved changes, and not otherwise", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    await shown();
    expect(navigate("/accounts")).toBe(true);                                    // nothing changed: no question
    window.history.replaceState(null, "", "/balances/12");
    expect(ask).not.toHaveBeenCalled();
    fireEvent.change(amountBox(), { target: { value: "325.5" } });
    expect(navigate("/accounts")).toBe(false);                                   // asked, and refused
    expect(ask).toHaveBeenCalledTimes(1);
    ask.mockReturnValue(true);
    expect(navigate("/accounts")).toBe(true);
  });
});

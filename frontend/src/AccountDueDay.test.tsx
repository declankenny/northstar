// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage as Account } from "./api";
import { AccountPage } from "./AccountPage";
import { clearFlash } from "./flash";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), editAccount: vi.fn(),
}));

import { editAccount, fetchAccount } from "./api";

const account = (over: Partial<Account> = {}): Account => ({
  id: 7, name: "Visa Card", currency: { code: "USD", name: "US Dollar", minor_units: 2 }, class_name: "Liability", type_id: 4, type_name: "Credit card", is_open: true,
  notes: null, website: null, website_removed: [], due_day: null, next_due: null, stale_after_days: 30, balance_count: 0, earliest_date: null, last_date: null,
  last_cents: null, days_since: null, stale: false, types: [{ id: 4, name: "Credit card" }], other_class: { id: 1, name: "Asset", types: [] }, today: "2026-11-15", ...over,
});

beforeEach(() => window.history.replaceState(null, "", "/accounts/7"));
afterEach(() => {
  cleanup();
  clearFlash();
  vi.resetAllMocks();
});

const openEdit = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "More actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Edit account" }));
  return await screen.findByRole("dialog");
};

const tile = () => screen.getByText("Next due").closest(".tile") as HTMLElement;

describe("the Next due tile on a liability's page", () => {
  it("shows the date, how far away it is, the day and that payments are not tracked", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ due_day: 20, next_due: "2026-11-20" }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(tile().textContent).toContain("in 5 days");
    expect(tile().textContent).toContain("The 20th of each month. Payments aren't tracked.");
    expect(tile().querySelector(".val")!.textContent).not.toBe("—");
  });

  it("says Due today, as a warning, when the date is today", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ due_day: 15, next_due: "2026-11-15" }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(within(tile()).getByText("Due today").className).toBe("w");
  });

  it("says there is no due day, with a dash", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(tile().querySelector(".val")!.textContent).toBe("—");
    expect(tile().textContent).toContain("No due day set. Payments aren't tracked.");
  });

  it("has no date for a closed account, and says so", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ is_open: false, due_day: 20, next_due: null }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(tile().querySelector(".val")!.textContent).toBe("—");
    expect(tile().textContent).toContain("The account is closed, so there is no date.");
  });

  it("is not on an asset's page, which keeps four tiles", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ class_name: "Asset" }));
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(screen.queryByText("Next due")).toBeNull();
    expect(document.querySelector(".tiles")!.classList.contains("five")).toBe(false);
  });

  it("gives a liability's tiles the five-column class", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(document.querySelector(".tiles")!.classList.contains("five")).toBe(true);
  });
});

describe("the due day in the Edit account dialog", () => {
  it("is a number field with the agreed hint, filled with the stored day", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ due_day: 15, next_due: "2026-11-15" }));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    const box = within(dialog).getByLabelText(/Payment due day/) as HTMLInputElement;
    expect([box.type, box.min, box.max, box.value]).toEqual(["number", "1", "31", "15"]);
    expect(within(dialog).getByText("The day of the month it is due, 1 to 31.")).toBeTruthy();
  });

  it("sends the day as a number, and null when the field is left blank", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ due_day: 15, next_due: "2026-11-15" }));
    vi.mocked(editAccount).mockResolvedValue(account({ due_day: 3, next_due: "2026-12-03" }));
    render(<AccountPage id={7} isAdmin />);
    let dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText(/Payment due day/), { target: { value: "3" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(editAccount).toHaveBeenCalledWith(7, { name: "Visa Card", type_id: 4, notes: "", website: "", due_day: 3 }));

    dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText(/Payment due day/), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(editAccount).toHaveBeenLastCalledWith(7, { name: "Visa Card", type_id: 4, notes: "", website: "", due_day: null }));
  });

  it("is not offered for an asset, and is not sent", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ class_name: "Asset" }));
    vi.mocked(editAccount).mockResolvedValue(account({ class_name: "Asset" }));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    expect(within(dialog).queryByLabelText(/Payment due day/)).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(editAccount).toHaveBeenCalledWith(7, { name: "Visa Card", type_id: 4, notes: "", website: "" }));
  });

  it("shows the server's refusal in the dialog and keeps it open", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    vi.mocked(editAccount).mockRejectedValue(new Error("The due day must be a whole number from 1 to 31."));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText(/Payment due day/), { target: { value: "15" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("whole number from 1 to 31");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeletedAccount, DeletedAccounts as Data } from "./api";
import { DeletedAccounts } from "./DeletedAccounts";
import { clearFlash, peekFlash } from "./flash";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchDeletedAccounts: vi.fn(), restoreAccount: vi.fn() }));

import { fetchDeletedAccounts, restoreAccount } from "./api";

const entry = (over: Partial<DeletedAccount> = {}): DeletedAccount => ({
  id: 7, name: "Old joint savings", type_name: "Savings", is_open: true, deleted_by: "Sam", deleted_on: "2026-11-02", purge_on: "2027-01-31", balance_count: 12, name_taken: false, ...over,
});
const data = (accounts: DeletedAccount[], over: Partial<Data> = {}): Data => ({ cleanup_on: true, retention_days: 90, accounts, ...over });

beforeEach(() => window.history.replaceState(null, "", "/deleted-accounts"));
afterEach(() => {
  cleanup();
  clearFlash();
  vi.resetAllMocks();
});

describe("the Deleted accounts page", () => {
  it("lists each account with its type, when it was deleted and when it goes for good", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry()]));
    render(<DeletedAccounts />);
    const row = (await screen.findByText("Old joint savings")).closest("tr") as HTMLElement;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Old joint savings", "Savings", "Sam", "Nov 2, 2026", "Jan 31, 2027", "Restore account…"]);
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual(["Account", "Type", "Deleted by", "Deleted", "Permanently deleted on", ""]);
  });

  it("marks a closed account", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry({ is_open: false })]));
    render(<DeletedAccounts />);
    expect(within((await screen.findByText("Old joint savings")).closest("tr") as HTMLElement).getByText("Closed")).toBeTruthy();
  });

  it("says nothing is scheduled, and why, when the cleanup is off", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry({ purge_on: null })], { cleanup_on: false }));
    render(<DeletedAccounts />);
    expect(await screen.findByText("Not scheduled")).toBeTruthy();
    expect(screen.getByText(/switched off, so deleted accounts are kept/)).toBeTruthy();
  });

  it("says so when nothing is deleted", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([]));
    render(<DeletedAccounts />);
    expect(await screen.findByText(/No deleted accounts/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("confirms, restores, leaves a notice and opens the account", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry()]));
    vi.mocked(restoreAccount).mockResolvedValue({ id: 7, name: "Old joint savings", balance_count: 12 });
    render(<DeletedAccounts />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore account…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/12 balances its deletion hid/)).toBeTruthy();
    expect(within(dialog).getByText(/stays open/)).toBeTruthy();
    expect(within(dialog).queryByLabelText("New name")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore account" }));
    await waitFor(() => expect(window.location.pathname).toBe("/accounts/7"));
    expect(restoreAccount).toHaveBeenCalledWith(7, undefined);
    expect(peekFlash()).toBe("Old joint savings was restored with 12 balances.");
  });

  it("says a closed account stays closed", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry({ is_open: false })]));
    render(<DeletedAccounts />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore account…" }));
    expect(within(await screen.findByRole("dialog")).getByText(/stays closed/)).toBeTruthy();
  });

  it("asks for a new name when the name is in use, and restores under it", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry({ name_taken: true })]));
    vi.mocked(restoreAccount).mockResolvedValue({ id: 7, name: "Old joint savings (old)", balance_count: 0 });
    render(<DeletedAccounts />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore account…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Another account is now called Old joint savings/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("New name"), { target: { value: "Old joint savings (old)" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore account" }));
    await waitFor(() => expect(restoreAccount).toHaveBeenCalledWith(7, "Old joint savings (old)"));
    expect(peekFlash()).toBe("Old joint savings (old) was restored.");
  });

  it("cannot restore under a blank name", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValue(data([entry({ name_taken: true })]));
    render(<DeletedAccounts />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore account…" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("New name"), { target: { value: "  " } });
    expect((within(dialog).getByRole("button", { name: "Restore account" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("a refusal stays in the dialog, nothing opens, and a name taken since asks for a new one", async () => {
    vi.mocked(fetchDeletedAccounts).mockResolvedValueOnce(data([entry()])).mockResolvedValue(data([entry({ name_taken: true })]));
    vi.mocked(restoreAccount).mockRejectedValue(new Error('An account named "Old joint savings" already exists. Choose a different name.'));
    render(<DeletedAccounts />);
    fireEvent.click(await screen.findByRole("button", { name: "Restore account…" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Restore account" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
    expect(await screen.findByLabelText("New name")).toBeTruthy();
    expect(window.location.pathname).toBe("/deleted-accounts");
    expect(peekFlash()).toBeNull();
  });
});

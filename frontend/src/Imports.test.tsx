// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ImportEntry, ImportRegister, UndoPlan, UndoRefusal } from "./api";
import { Imports } from "./Imports";
import { setLocale, US_ENGLISH } from "./locale";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchImports: vi.fn(), fetchUndoPlan: vi.fn(), undoImport: vi.fn() }));

import { fetchImports, fetchUndoPlan, undoImport } from "./api";

const entry = (over: Partial<ImportEntry> = {}): ImportEntry => ({
  id: 1, date: "2026-11-02", by: "Demo Admin", account_id: 7, account_name: "Demo Savings", account_deleted: false, account_open: true,
  file: "savings-2026.csv", added: 297, replaced: 3, reverted_on: null, ...over,
});

const register = (imports: ImportEntry[], more = false): ImportRegister => ({ imports, more, limit: 25 });

beforeEach(() => window.history.replaceState(null, "", "/imports"));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the Imports page", () => {
  it("lists each import with its date, who, account, file and counts, and links to the account", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([entry()]));
    render(<Imports />);
    const row = (await screen.findByText("savings-2026.csv")).closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells).toEqual(["Nov 2, 2026", "Demo Admin", "Demo Savings", "savings-2026.csv", "297", "3", "Undo…"]);
    expect(within(row).getByRole("link", { name: "Demo Savings" }).getAttribute("href")).toBe("/accounts/7");
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent))
      .toEqual(["Import Date", "Import By", "Account", "File Name", "Added", "Replaced", "Status"]);
  });

  it("marks a closed account, a deleted one and one it cannot name", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([
      entry({ id: 3, file: "a.csv", account_open: false }),
      entry({ id: 2, file: "b.csv", account_deleted: true }),
      entry({ id: 1, file: "c.csv", account_id: null, account_name: null }),
    ]));
    render(<Imports />);
    const rowOf = async (file: string) => (await screen.findByText(file)).closest("tr") as HTMLElement;
    expect(within(await rowOf("a.csv")).getByText("Closed")).toBeTruthy();
    expect(within(await rowOf("b.csv")).getByText("(deleted account)")).toBeTruthy();
    expect(within(await rowOf("b.csv")).queryByRole("link")).toBeNull();
    expect(within(await rowOf("c.csv")).getByText("Unknown account")).toBeTruthy();
  });

  it("shows every date in the person's own format, in the register and in the undo dialog", async () => {
    setLocale({ ...US_ENGLISH, tag: "de-DE", label: "German (Germany)", date_template: "{day2}.{month2}.{year}" });
    try {
      vi.mocked(fetchImports).mockResolvedValue(register([entry({ reverted_on: "2026-11-05" })]));
      render(<Imports />);
      const row = (await screen.findByText("savings-2026.csv")).closest("tr") as HTMLElement;
      const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent);
      expect(cells[0]).toBe("02.11.2026");
      expect(within(row).getByText("Reverted on 05.11.2026")).toBeTruthy();
      expect(screen.queryByText(/2026-11/)).toBeNull();
    } finally {
      setLocale(null);
    }
  });

  it("says when an import was reverted, and offers no Undo for it", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([entry({ reverted_on: "2026-11-05" })]));
    render(<Imports />);
    expect(await screen.findByText("Reverted on Nov 5, 2026")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull();
  });

  it("says there are older imports when the list is cut off, and only then", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([entry()], true));
    render(<Imports />);
    expect(await screen.findByText("Showing the newest 25 imports. Older ones are not listed.")).toBeTruthy();
    cleanup();
    vi.mocked(fetchImports).mockResolvedValue(register([entry()], false));
    render(<Imports />);
    await screen.findByText("savings-2026.csv");
    expect(screen.queryByText(/Older ones are not listed/)).toBeNull();
  });

  it("has a message instead of an empty table", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([]));
    render(<Imports />);
    expect(await screen.findByText(/No imports yet/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows the server's message when it cannot load", async () => {
    vi.mocked(fetchImports).mockRejectedValue(new Error("Only admins can do that."));
    render(<Imports />);
    expect((await screen.findByRole("alert")).textContent).toBe("Only admins can do that.");
  });
});

const plan = (over: Partial<UndoPlan> = {}): UndoPlan => ({
  import_id: 1, file: "savings-2026.csv", date: "2026-11-02", by: "Demo Admin", account_id: 7, account_name: "Demo Savings",
  delete: 297, restore: 3, ...over,
});

const refusal = (over: Partial<UndoRefusal> = {}): UndoRefusal => ({
  refused: true, message: "Some of this import's balances have changed since, and Undo does not overwrite later changes.",
  reason: "changed", blocked: [{ date: "2026-03-31", why: "Edited since the import" }, { date: "2026-04-30", why: "Deleted since the import" }],
  more: 4, ...over,
});

async function openUndo() {
  render(<Imports />);
  fireEvent.click(await screen.findByRole("button", { name: /Undo/ }));
}

describe("Undo on the Imports page", () => {
  beforeEach(() => vi.mocked(fetchImports).mockResolvedValue(register([entry()])));

  it("asks what it would do and says so, before anything is written", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(plan());
    await openUndo();
    await screen.findByRole("button", { name: "Undo import" });
    const dialog = screen.getByRole("dialog", { name: "Undo this import?" });
    expect(dialog.textContent).toContain("savings-2026.csv, imported into Demo Savings on Nov 2, 2026 by Demo Admin.");
    expect(dialog.textContent).toContain("297 balances the import added will be deleted.");
    expect(dialog.textContent).toContain("3 balances it replaced will get their old amounts, notes and sources back.");
    expect(dialog.textContent).toContain("An undo cannot be undone");
    expect(fetchUndoPlan).toHaveBeenCalledWith(1, expect.anything());
    expect(undoImport).not.toHaveBeenCalled();
  });

  it("leaves out the line for something the import did not do", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(plan({ restore: 0, delete: 1 }));
    await openUndo();
    await screen.findByRole("button", { name: "Undo import" });
    const dialog = screen.getByRole("dialog", { name: "Undo this import?" });
    expect(dialog.textContent).toContain("1 balance the import added will be deleted.");
    expect(dialog.textContent).not.toContain("replaced");
  });

  it("does nothing on Cancel", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(plan());
    await openUndo();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(undoImport).not.toHaveBeenCalled();
  });

  it("undoes it on confirming, shows the register as it now is and says what was done", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(plan());
    vi.mocked(undoImport).mockResolvedValue({ deleted: 297, restored: 3, after: register([entry({ reverted_on: "2026-11-05" })]) });
    await openUndo();
    fireEvent.click(await screen.findByRole("button", { name: "Undo import" }));
    expect(await screen.findByText("Reverted on Nov 5, 2026")).toBeTruthy();
    expect(undoImport).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Undid savings-2026.csv: 297 balances deleted and 3 restored.");
  });

  it("names the dates in the way, with how many more, when the import cannot be undone", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(refusal());
    await openUndo();
    const dialog = await screen.findByRole("dialog", { name: "This import can’t be undone yet" });
    expect(within(dialog).getAllByRole("row").map((row) => row.textContent)).toEqual([
      "Mar 31, 2026Edited since the import", "Apr 30, 2026Deleted since the import"]);
    expect(dialog.textContent).toContain("and 4 more.");
    expect(dialog.textContent).toContain("Nothing was changed. Fix these balances by hand, then try Undo again.");
    expect(within(dialog).queryByRole("button", { name: "Undo import" })).toBeNull();
  });

  it("says plainly when the account is closed", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(refusal({
      reason: "account_closed", blocked: [], more: 0,
      message: "Demo Savings is closed, and a closed account takes no changes. Reopen it, then try Undo again.",
    }));
    await openUndo();
    const dialog = await screen.findByRole("dialog", { name: "This import can’t be undone yet" });
    expect(dialog.textContent).toContain("Demo Savings is closed");
    expect(within(dialog).queryByRole("row")).toBeNull();
  });

  it("shows a refusal that comes at the last moment, and reloads the register when it is closed", async () => {
    vi.mocked(fetchUndoPlan).mockResolvedValue(plan());
    vi.mocked(undoImport).mockResolvedValue(refusal({ blocked: [{ date: "2026-02-28", why: "Edited since the import" }], more: 0 }));
    await openUndo();
    fireEvent.click(await screen.findByRole("button", { name: "Undo import" }));
    const dialog = await screen.findByRole("dialog", { name: "This import can’t be undone yet" });
    expect(dialog.textContent).toContain("Feb 28, 2026");
    vi.mocked(fetchImports).mockClear();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await vi.waitFor(() => expect(fetchImports).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the server's message when the plan cannot be fetched", async () => {
    vi.mocked(fetchUndoPlan).mockRejectedValue(new Error("That import no longer exists."));
    await openUndo();
    const dialog = await screen.findByRole("dialog");
    expect((await within(dialog).findByRole("alert")).textContent).toBe("That import no longer exists.");
  });
});

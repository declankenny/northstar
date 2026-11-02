// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ImportEntry, ImportRegister } from "./api";
import { Imports } from "./Imports";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchImports: vi.fn() }));

import { fetchImports } from "./api";

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
    expect(cells).toEqual(["2026-11-02", "Demo Admin", "Demo Savings", "savings-2026.csv", "297", "3", ""]);
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

  it("says when an import was reverted", async () => {
    vi.mocked(fetchImports).mockResolvedValue(register([entry({ reverted_on: "2026-11-05" })]));
    render(<Imports />);
    expect(await screen.findByText("Reverted on 2026-11-05")).toBeTruthy();
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

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdatePage, UpdateRow } from "./api";
import { Modal } from "./Dialogs";
import { UpdateBalances } from "./UpdateBalances";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchUpdate: vi.fn() }));

import { fetchUpdate } from "./api";

const row = (id: number, name: string, class_name: UpdateRow["class_name"]): UpdateRow => ({
  id, name, class_name, type_name: "Savings", stale_after_days: 30, last_date: null, last_cents: null,
  days_since: null, stale: false, existing_cents: null,
});
const page: UpdatePage = {
  date: "2026-10-30", today: "2026-10-30", saved: null,
  rows: [row(1, "Checking", "Asset"), row(2, "Savings", "Asset"), row(3, "Card", "Liability")],
};

afterEach(cleanup);

describe("Update balances: moving between the amount boxes", () => {
  const box = (name: string) => screen.getByRole("textbox", { name: `New balance for ${name}` });

  beforeEach(() => {
    vi.mocked(fetchUpdate).mockResolvedValue(page);
  });

  it("starts in the first box, and the arrow keys and Enter move down and up the list", async () => {
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Checking" });
    expect(document.activeElement).toBe(box("Checking"));

    fireEvent.keyDown(box("Checking"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(box("Savings"));
    fireEvent.keyDown(box("Savings"), { key: "Enter" });
    expect(document.activeElement).toBe(box("Card"));
    fireEvent.keyDown(box("Card"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(box("Savings"));
  });

  it("stays on the first box on ArrowUp, and goes from the last box to Save once there is something to save", async () => {
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Checking" });
    fireEvent.keyDown(box("Checking"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(box("Checking"));

    fireEvent.change(box("Card"), { target: { value: "120.50" } }); // Save is disabled until an amount is typed
    fireEvent.keyDown(box("Card"), { key: "Enter" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Save balances" }));
  });

  it("keeps the keys' own work from happening: the arrows do not move the caret or submit anything", async () => {
    render(<UpdateBalances />);
    await screen.findByRole("textbox", { name: "New balance for Checking" });
    // fireEvent returns false when the handler called preventDefault.
    expect(fireEvent.keyDown(box("Checking"), { key: "ArrowDown" })).toBe(false);
    expect(fireEvent.keyDown(box("Savings"), { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(box("Savings"), { key: "a" })).toBe(true);
  });
});

describe("Dialogs: the keyboard", () => {
  it("Escape closes the box, and other keys do not", () => {
    const onClose = vi.fn();
    render(<Modal title="Edit account" onClose={onClose}><button>Save</button></Modal>);
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stops listening for Escape once the box is gone", () => {
    const onClose = vi.fn();
    const { unmount } = render(<Modal title="Edit account" onClose={onClose}><button>Save</button></Modal>);
    unmount();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("is a labelled modal dialog, so a screen reader announces it", () => {
    render(<Modal title="Edit account" onClose={() => {}}><button>Save</button></Modal>);
    const dialog = screen.getByRole("dialog", { name: "Edit account" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});

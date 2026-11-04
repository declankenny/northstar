// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TypeList } from "./api";
import { AccountTypes } from "./AccountTypes";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchTypes: vi.fn() }));

import { fetchTypes } from "./api";

const list = (defaultDays: number): TypeList => ({
  types: [{ id: 1, name: "Checking", class_id: 1, class_name: "Asset", stale_after_days: 35, account_count: 0, deleted_account_count: 0 }],
  classes: [{ id: 1, name: "Asset" }, { id: 2, name: "Liability" }],
  default_stale_after_days: defaultDays,
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the Account types page", () => {
  it("starts a new type at the server's default stale-after days", async () => {
    vi.mocked(fetchTypes).mockResolvedValue(list(30));
    render(<AccountTypes />);
    fireEvent.click(await screen.findByRole("button", { name: "Add type" }));
    expect((screen.getByLabelText(/Stale after/) as HTMLInputElement).value).toBe("30");
  });

  it("follows the default the server sends, and keeps an existing type's own days when it is edited", async () => {
    vi.mocked(fetchTypes).mockResolvedValue(list(45));
    render(<AccountTypes />);
    fireEvent.click(await screen.findByRole("button", { name: "Add type" }));
    expect((screen.getByLabelText(/Stale after/) as HTMLInputElement).value).toBe("45");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Actions for Checking" }));
    fireEvent.click(await screen.findByText("Edit"));
    expect((screen.getByLabelText(/Stale after/) as HTMLInputElement).value).toBe("35");
  });
});

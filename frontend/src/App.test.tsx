// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Me } from "./api";
import { App } from "./App";
import { deferred } from "./testing";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchMe: vi.fn(), fetchVersion: vi.fn() }));

import { fetchMe, fetchVersion } from "./api";

const me = (over: Partial<Me> = {}): Me => ({
  id: 1, email: "test@example.com", display_name: "Test Admin", is_admin: true, theme: "dark",
  currency: { code: "USD", name: "US Dollar", minor_units: 2 },
  locale: { tag: "en-US", label: "English (United States)", decimal_mark: ".", group_mark: ",",
    date_template: "{month_short} {day}, {year}", currency_position: "prefix", currency_code_spacing: "\u00a0" },
  ...over,
});

beforeEach(() => {
  window.history.replaceState(null, "", "/profile");
  vi.mocked(fetchVersion).mockResolvedValue({ version: "0.2.0" } as never);
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the signed-in shell", () => {
  it("shows nothing but a waiting message until the person's locale is known", async () => {
    const answer = deferred<Me>();
    vi.mocked(fetchMe).mockReturnValue(answer.promise);
    render(<App />);
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Accounts" })).toBeNull();
    answer.resolve(me());
    expect(await screen.findByRole("link", { name: "Accounts" })).toBeTruthy();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("says why and offers to try again when the person's locale cannot be loaded, and then carries on", async () => {
    vi.mocked(fetchMe).mockRejectedValueOnce(new Error("The server answered 500")).mockResolvedValue(me());
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toBe("The server answered 500");
    expect(screen.queryByRole("link", { name: "Accounts" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Accounts" })).toBeTruthy();
    expect(fetchMe).toHaveBeenCalledTimes(2);
  });

  it("does not wait for anything on the sign-in page", () => {
    window.history.replaceState(null, "", "/login");
    render(<App />);
    expect(fetchMe).not.toHaveBeenCalled();
  });
});

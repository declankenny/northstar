// @vitest-environment jsdom
// The screens of OIDC sign-in other than the sign-in page: the Sign-in column on Users, the reset-password dialog for someone with
// no password, and the Profile of someone who signs in only through the identity provider. Synthetic data only.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Me, type UserRow } from "./api";
import { US_ENGLISH } from "./locale";
import { Profile } from "./Profile";
import { Users } from "./Users";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchUsers: vi.fn(), fetchLocales: vi.fn(), resetPassword: vi.fn(),
}));

import { fetchLocales, fetchUsers } from "./api";

const me = (over: Partial<Me> = {}): Me => ({
  id: 1, email: "alex@example.test", display_name: "Alex Example", is_admin: true, theme: "dark", has_password: true, currency: null,
  locale: { ...US_ENGLISH }, ...over,
});

const user = (id: number, name: string, sign_in: UserRow["sign_in"]): UserRow => ({
  id, email: `${name.split(" ")[0].toLowerCase()}@example.test`, display_name: name, is_admin: id === 1, created_at: "2026-11-02T10:00:00Z", sign_in,
});

const USERS = [user(1, "Alex Example", "both"), user(2, "Sam Example", "oidc"), user(3, "Robin Example", "local"), user(4, "Pat Example", "none")];

beforeEach(() => {
  vi.mocked(fetchUsers).mockResolvedValue(USERS);
  vi.mocked(fetchLocales).mockResolvedValue({ locales: [{ tag: "en-US", label: "English (United States)" }], default: "en-US" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the Users page", () => {
  it("has a Sign-in column that says Local, OIDC, or Local and OIDC, with the word OIDC and not a provider's name", async () => {
    render(<Users me={me()} onMe={vi.fn()} />);
    await screen.findByText("Sam Example");
    expect(screen.getByRole("columnheader", { name: "Sign-in" })).toBeTruthy();
    const heads = screen.getAllByRole("columnheader").map((head) => head.textContent);
    expect(heads).toEqual(["Name", "Email", "Role", "Sign-in", "Added", ""]);
    const cell = (name: string) => within(screen.getByText(name).closest("tr")!).getAllByRole("cell")[3].textContent;
    expect(cell("Alex Example")).toBe("Local and OIDC");
    expect(cell("Sam Example")).toBe("OIDC");
    expect(cell("Robin Example")).toBe("Local");
    expect(cell("Pat Example")).toBe("None");
  });

  async function openReset(email: string) {
    render(<Users me={me()} onMe={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: `Actions for ${email}` }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Reset password" }));
    return screen.findByRole("dialog");
  }

  it("tells an admin that someone who signs in only through the provider has no password, and that setting one lets them use it", async () => {
    const dialog = await openReset("sam@example.test");
    expect(within(dialog).getByText(/Sam signs in through the identity provider and has no password today, so this also lets them use password sign-in while it is turned on\./)).toBeTruthy();
    expect(within(dialog).getByText(/They are signed out everywhere and use this to sign in again\./)).toBeTruthy();
  });

  it("says nothing about the provider to someone who already has a password", async () => {
    const dialog = await openReset("robin@example.test");
    expect(within(dialog).getByText("They are signed out everywhere and use this to sign in again.")).toBeTruthy();
    expect(dialog.textContent).not.toContain("identity provider");
  });

  it("makes Cancel a plain button like Set password, not a ghost one", async () => {
    const dialog = await openReset("robin@example.test");
    expect(within(dialog).getByRole("button", { name: "Cancel" }).className).toBe("btn");
    expect(within(dialog).getByRole("button", { name: "Set password" }).className).toBe("btn");
  });
});

describe("the Profile of someone who signs in only through the provider", () => {
  const props = { onChange: vi.fn(), onTheme: vi.fn() };

  it("explains how they sign in, naming the provider, instead of a form that could not succeed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ local: true, oidc: true, provider: "Pocket ID" }), { status: 200 })));
    render(<Profile me={me({ has_password: false })} {...props} />);
    expect(await screen.findByText("You sign in with Pocket ID, so Northstar has no password for you. Change your password or manage your account there.")).toBeTruthy();
    expect(screen.queryByLabelText("Current password")).toBeNull();
    expect(screen.queryByRole("button", { name: "Change password" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Password" })).toBeTruthy();
  });

  it("uses a plain name when the provider has none or cannot be asked", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    render(<Profile me={me({ has_password: false })} {...props} />);
    expect(screen.getByText(/You sign in with your identity provider, so Northstar has no password for you\./)).toBeTruthy();
  });

  it("keeps the change-password form for someone who has a password, and asks nothing of the server for it", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Profile me={me({ has_password: true })} {...props} />);
    expect(screen.getByLabelText("Current password")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change password" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

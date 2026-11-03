// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { signOut } from "./api";
import { SignIn } from "./SignIn";

const assign = vi.fn();
const realLocation = window.location;

/** Pretend the browser is at an address, with `assign` recorded instead of leaving the test page. */
function visit(search: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { pathname: "/login", search, assign },
  });
}

function answer(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => visit(""));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  assign.mockReset();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

describe("the sign-in page", () => {
  it("asks for an email and a password, in fields a password manager recognises", () => {
    render(<SignIn />);
    expect(screen.getByLabelText("Email")).toHaveProperty("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveProperty("autocomplete", "current-password");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it("sends what was typed and the address asked for, then goes where the server says with a full page load", async () => {
    visit("?next=%2Faccounts%2F7");
    const fetchMock = answer(200, { next: "/accounts/7" });
    vi.stubGlobal("fetch", fetchMock);
    render(<SignIn />);
    fill("a@example.com", "synthetic-pass-123");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/accounts/7"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(JSON.parse(init.body)).toEqual({ email: "a@example.com", password: "synthetic-pass-123", next: "/accounts/7" });
  });

  it("asks for the site root when no address was given, and goes where the server decides", async () => {
    const fetchMock = answer(200, { next: "/dashboard" });
    vi.stubGlobal("fetch", fetchMock);
    render(<SignIn />);
    fill("a@example.com", "synthetic-pass-123");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/dashboard"));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).next).toBe("/");
  });

  it("shows a refusal, keeps the email and clears the password", async () => {
    vi.stubGlobal("fetch", answer(400, { detail: "That email and password don't match." }));
    render(<SignIn />);
    fill("a@example.com", "wrong-password-123");
    expect((await screen.findByRole("alert")).textContent).toBe("That email and password don't match.");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("a@example.com");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows the throttling message as the server words it", async () => {
    vi.stubGlobal("fetch", answer(429, { detail: "Too many sign-in attempts. Try again in about 15 minutes." }));
    render(<SignIn />);
    fill("a@example.com", "synthetic-pass-123");
    expect((await screen.findByRole("alert")).textContent).toBe("Too many sign-in attempts. Try again in about 15 minutes.");
  });

  it("does not ask who is signed in, which would send a signed-out visitor straight back here", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/login");
    visit("");
    Object.defineProperty(window.location, "pathname", { configurable: true, value: "/login" });
    render(<App />);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("signing out", () => {
  it("ends the session on the server and then goes to the sign-in page", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await signOut();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("goes to the sign-in page when the session had already ended", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    await signOut();
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("does not claim to be signed out when the server could not be asked", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    await expect(signOut()).rejects.toThrow("Could not sign out");
    expect(assign).not.toHaveBeenCalled();
  });

  it("does not claim to be signed out when the server failed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));
    await expect(signOut()).rejects.toThrow("Could not sign out");
    expect(assign).not.toHaveBeenCalled();
  });
});

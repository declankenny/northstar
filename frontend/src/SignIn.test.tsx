// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { signOut } from "./api";
import { SETUP_EMAIL_KEY } from "./Setup";
import { providerMessage, SignIn } from "./SignIn";

const assign = vi.fn();
const realLocation = window.location;

/** Pretend the browser is at an address, with `assign` recorded instead of leaving the test page. */
function visit(search: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { pathname: "/login", search, assign },
  });
}

const LOCAL_ONLY = { local: true, oidc: false, provider: null };

/** A fetch that answers the sign-in methods with `methods` and the password sign-in with `login`, and records every call. */
function server(login: Response = new Response(JSON.stringify({ next: "/dashboard" }), { status: 200 }), methods: unknown = LOCAL_ONLY) {
  return vi.fn((url: string) => {
    if (url === "/api/auth/methods") return Promise.resolve(new Response(JSON.stringify(methods), { status: 200 }));
    if (url === "/api/auth/login") return Promise.resolve(login.clone());
    return Promise.reject(new Error(`unexpected request to ${url}`));
  });
}

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const loginCalls = (mock: ReturnType<typeof server>) => mock.mock.calls.filter(([url]) => url === "/api/auth/login");
const bodyOf = (call: unknown[]) => JSON.parse((call[1] as { body: string }).body);

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
  sessionStorage.clear();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

describe("the sign-in page", () => {
  it("asks for an email and a password, in fields a password manager recognises", async () => {
    vi.stubGlobal("fetch", server());
    render(<SignIn />);
    expect(await screen.findByLabelText("Email")).toHaveProperty("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveProperty("autocomplete", "current-password");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it("sends what was typed and the address asked for, then goes where the server says with a full page load", async () => {
    visit("?next=%2Faccounts%2F7");
    const fetchMock = server(reply(200, { next: "/accounts/7" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SignIn />);
    await screen.findByLabelText("Email");
    fill("a@example.com", "synthetic-pass-123");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/accounts/7"));
    expect(bodyOf(loginCalls(fetchMock)[0])).toEqual({ email: "a@example.com", password: "synthetic-pass-123", next: "/accounts/7" });
  });

  it("asks for the site root when no address was given, and goes where the server decides", async () => {
    const fetchMock = server(reply(200, { next: "/dashboard" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SignIn />);
    await screen.findByLabelText("Email");
    fill("a@example.com", "synthetic-pass-123");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/dashboard"));
    expect(bodyOf(loginCalls(fetchMock)[0]).next).toBe("/");
  });

  it("shows a refusal, keeps the email and clears the password", async () => {
    vi.stubGlobal("fetch", server(reply(400, { detail: "That email and password don't match." })));
    render(<SignIn />);
    await screen.findByLabelText("Email");
    fill("a@example.com", "wrong-password-123");
    expect((await screen.findByRole("alert")).textContent).toBe("That email and password don't match.");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("a@example.com");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows the throttling message as the server words it", async () => {
    vi.stubGlobal("fetch", server(reply(429, { detail: "Too many sign-in attempts. Try again in about 15 minutes." })));
    render(<SignIn />);
    await screen.findByLabelText("Email");
    fill("a@example.com", "synthetic-pass-123");
    expect((await screen.findByRole("alert")).textContent).toBe("Too many sign-in attempts. Try again in about 15 minutes.");
  });

  it("does not ask who is signed in, which would send a signed-out visitor straight back here", async () => {
    const fetchMock = server();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/login");
    visit("");
    Object.defineProperty(window.location, "pathname", { configurable: true, value: "/login" });
    render(<App />);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    await screen.findByLabelText("Email");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/auth/methods"]);   // the public question only, never /api/me
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

describe("the sign-in page right after first-run setup", () => {
  it("says setup is complete and starts with the new administrator's email filled in, never a password", async () => {
    vi.stubGlobal("fetch", server());
    visit("?setup=complete");
    sessionStorage.setItem(SETUP_EMAIL_KEY, "alex@example.com");
    render(<SignIn />);
    await screen.findByLabelText("Email");
    expect(screen.getByRole("heading", { name: "Setup complete" })).toBeTruthy();
    expect(screen.getByText("Your administrator account and household settings are ready.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sign in to Northstar" })).toBeTruthy();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("alex@example.com");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(screen.getByLabelText("Password")); // the email is known, so the password is next
    expect(sessionStorage.getItem(SETUP_EMAIL_KEY)).toBeNull(); // read once
  });

  it("works without the remembered email, as when the browser blocks storage", async () => {
    vi.stubGlobal("fetch", server());
    visit("?setup=complete");
    render(<SignIn />);
    await screen.findByLabelText("Email");
    expect(screen.getByRole("heading", { name: "Setup complete" })).toBeTruthy();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(screen.getByLabelText("Email"));
  });

  it("is the ordinary sign-in page otherwise, and ignores a remembered email", async () => {
    vi.stubGlobal("fetch", server());
    sessionStorage.setItem(SETUP_EMAIL_KEY, "alex@example.com");
    render(<SignIn />);
    await screen.findByLabelText("Email");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText("Setup complete")).toBeNull();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("");
  });
});

const BOTH = { local: true, oidc: true, provider: "Pocket ID" };
const PROVIDER_ONLY = { local: false, oidc: true, provider: "Pocket ID" };

describe("the sign-in page with an identity provider", () => {
  it("offers the provider's button above the password form, with the line between them", async () => {
    vi.stubGlobal("fetch", server(undefined, BOTH));
    const { container } = render(<SignIn />);
    const button = await screen.findByRole("button", { name: "Continue with Pocket ID" });
    expect(screen.getByText("or use your password")).toBeTruthy();
    const order = Array.from(container.querySelectorAll("button, input")).map((element) => element.getAttribute("name") ?? element.textContent);
    expect(order).toEqual(["Continue with Pocket ID", "email", "password", "Sign in"]);
    expect(button.closest("form")?.className).toBe("provider");
  });

  it("goes to the provider by navigating to Northstar's own address, with the address asked for, not by posting a form", async () => {
    visit("?next=%2Faccounts%3Ffilter%3Dopen");
    const fetchMock = server(undefined, BOTH);
    vi.stubGlobal("fetch", fetchMock);
    render(<SignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Pocket ID" }));
    expect(assign).toHaveBeenCalledWith("/api/auth/oidc/login?next=%2Faccounts%3Ffilter%3Dopen");
    expect(loginCalls(fetchMock)).toHaveLength(0);
  });

  it("asks for the site root when no address was given", async () => {
    vi.stubGlobal("fetch", server(undefined, BOTH));
    render(<SignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Pocket ID" }));
    expect(assign).toHaveBeenCalledWith("/api/auth/oidc/login?next=%2F");
  });

  it("is the button alone, with no password form and no line, when password sign-in is off", async () => {
    vi.stubGlobal("fetch", server(undefined, PROVIDER_ONLY));
    render(<SignIn />);
    await screen.findByRole("button", { name: "Continue with Pocket ID" });
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.queryByText("or use your password")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
  });

  it("shows nothing to sign in with until the server has said which ways are on", async () => {
    let answer: (response: Response) => void = () => {};
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { answer = resolve; })));
    render(<SignIn />);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    answer(reply(200, PROVIDER_ONLY));
    await screen.findByRole("button", { name: "Continue with Pocket ID" });
  });

  it("falls back to the password form when the server cannot be asked, and offers no provider", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    render(<SignIn />);
    expect(await screen.findByLabelText("Email")).toBeTruthy();
    expect(screen.queryByText(/Continue with/)).toBeNull();
  });

  it("names the button for a provider that has no name set", async () => {
    vi.stubGlobal("fetch", server(undefined, { local: true, oidc: true, provider: null }));
    render(<SignIn />);
    expect(await screen.findByRole("button", { name: "Continue with your identity provider" })).toBeTruthy();
  });

  it("does not offer the provider when it is off", async () => {
    vi.stubGlobal("fetch", server(undefined, LOCAL_ONLY));
    render(<SignIn />);
    await screen.findByLabelText("Email");
    expect(screen.queryByText(/Continue with/)).toBeNull();
    expect(screen.queryByText("or use your password")).toBeNull();
  });

  it("does not put the cursor in the email field when there is a button to go to first", async () => {
    vi.stubGlobal("fetch", server(undefined, BOTH));
    render(<SignIn />);
    await screen.findByLabelText("Email");
    expect(document.activeElement).not.toBe(screen.getByLabelText("Email"));
  });
});

describe("what the page says when the provider sends the browser back", () => {
  const CODES = ["not_allowed", "email_unverified", "provider_unavailable", "cancelled", "invalid_token", "expired",
    "not_configured", "busy", "throttled"];

  it.each([
    ["not_allowed", "This account can't sign in to Northstar. Ask a Northstar admin for access."],
    ["email_unverified", "Pocket ID hasn't confirmed your email address. Verify it there, then try again."],
    ["provider_unavailable", "Couldn't reach Pocket ID. Try again, or use your password."],
  ])("says the agreed words for %s", async (code, words) => {
    visit(`?oidc_error=${code}`);
    vi.stubGlobal("fetch", server(undefined, BOTH));
    render(<SignIn />);
    expect((await screen.findByRole("alert")).textContent).toBe(words);
  });

  it("leaves the password out of the advice when password sign-in is off", async () => {
    visit("?oidc_error=provider_unavailable");
    vi.stubGlobal("fetch", server(undefined, PROVIDER_ONLY));
    render(<SignIn />);
    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't reach Pocket ID. Try again.");
  });

  it("uses a plain name when the provider has none, starting the sentence with a capital", () => {
    expect(providerMessage("email_unverified", null, true)).toBe("Your identity provider hasn't confirmed your email address. Verify it there, then try again.");
    expect(providerMessage("provider_unavailable", null, true)).toBe("Couldn't reach your identity provider. Try again, or use your password.");
  });

  it.each(CODES)("has words for %s that are not a code", (code) => {
    const words = providerMessage(code, "Pocket ID", true);
    expect(words).not.toContain("_");     // a sentence, not the code with its underscores
    expect(words.length).toBeGreaterThan(15);
  });

  it("says something plain for a code it does not know, and never shows the code", async () => {
    visit("?oidc_error=%3Cb%3Ewhatever%3C%2Fb%3E");
    vi.stubGlobal("fetch", server(undefined, BOTH));
    render(<SignIn />);
    const text = (await screen.findByRole("alert")).textContent!;
    expect(text).toBe("Sign-in with Pocket ID failed. Try again, or use your password.");
    expect(text).not.toContain("whatever");
  });

  it("shows no error when none came back", async () => {
    vi.stubGlobal("fetch", server(undefined, BOTH));
    render(<SignIn />);
    await screen.findByRole("button", { name: "Continue with Pocket ID" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a password refusal in place of the one that came back from the provider", async () => {
    visit("?oidc_error=not_allowed");
    vi.stubGlobal("fetch", server(reply(400, { detail: "That email and password don't match." }), BOTH));
    render(<SignIn />);
    await screen.findByLabelText("Email");
    fill("a@example.com", "wrong-password-123");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("That email and password don't match."));
  });
});

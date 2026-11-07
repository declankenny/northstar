// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SetupOptions } from "./api";
import { US_ENGLISH } from "./locale";
import { App } from "./App";
import { currencyCode, SETUP_COMPLETE_PATH, SETUP_EMAIL_KEY, Setup, zoneGroups } from "./Setup";

const assign = vi.fn();
const realLocation = window.location;

const GERMAN = { tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".", date_template: "{day2}.{month2}.{year}",
  currency_position: "suffix" as const, currency_code_spacing: " " };

const OPTIONS: SetupOptions = {
  currency: { value: null, locked: false },
  currencies: [{ code: "USD", name: "US Dollar", minor_units: 2 }, { code: "EUR", name: "Euro", minor_units: 2 }],
  locale: "en-US",
  locales: [US_ENGLISH, GERMAN],
  timezone: "UTC",
  timezones: ["America/Chicago", "Europe/London", "Etc/UTC", "UTC"],
};

type Reply = { status?: number; body?: unknown };
type Calls = { url: string; method: string; body: any }[];

/** Answer each request by its method and address. A reply may be a function, to answer differently the second time. */
function serve(replies: Record<string, Reply | (() => Reply)>): Calls {
  const calls: Calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const found = replies[`${method} ${url}`];
    if (!found) throw new Error(`unexpected request ${method} ${url}`);
    const { status = 200, body } = typeof found === "function" ? found() : found;
    return status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

function field(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillAccount(password = "synthetic-pass-123", confirm = password) {
  field("Display name", "Alex Morgan");
  field("Email", "alex@example.com");
  field("Password", password);
  field("Confirm password", confirm);
}

const submitButton = () => screen.getByRole("button", { name: "Create administrator and finish setup" });

beforeEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: { pathname: "/setup", search: "", assign } });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  assign.mockReset();
  sessionStorage.clear();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

describe("the setup token", () => {
  it("is asked for first, in a field that takes a paste, and a wrong one says so and asks again", async () => {
    const calls = serve({
      "GET /api/setup/status": { body: { state: "token" } },
      "POST /api/setup/token": { status: 400, body: { detail: "That isn't the setup token. Copy it from the container log." } },
    });
    render(<Setup />);
    expect(await screen.findByRole("heading", { name: "Welcome to Northstar" })).toBeTruthy();
    expect(screen.getByLabelText("Setup token")).toHaveProperty("placeholder", "Paste your setup token");
    field("Setup token", " not-the-token ");
    fireEvent.click(screen.getByRole("button", { name: "Continue to setup" }));
    expect((await screen.findByRole("alert")).textContent).toContain("isn't the setup token");
    expect(calls.find((c) => c.url === "/api/setup/token")!.body).toEqual({ token: " not-the-token " });
    expect(screen.queryByRole("heading", { name: "Set up Northstar" })).toBeNull();
    expect((screen.getByLabelText("Setup token") as HTMLInputElement).value).toBe("");
  });

  it("opens the form once it is accepted, without the token appearing in the address", async () => {
    serve({
      "GET /api/setup/status": { body: { state: "token" } },
      "POST /api/setup/token": { status: 204 },
      "GET /api/setup/options": { body: OPTIONS },
    });
    render(<Setup />);
    await screen.findByLabelText("Setup token");
    field("Setup token", "the-token");
    fireEvent.click(screen.getByRole("button", { name: "Continue to setup" }));
    expect(await screen.findByRole("heading", { name: "Set up Northstar" })).toBeTruthy();
    expect(assign).not.toHaveBeenCalled();
  });

  it("is not asked for again when this browser already has a setup session", async () => {
    serve({ "GET /api/setup/status": { body: { state: "form" } }, "GET /api/setup/options": { body: OPTIONS } });
    render(<Setup />);
    expect(await screen.findByRole("heading", { name: "Set up Northstar" })).toBeTruthy();
  });

  it("says setup is over, with a way to sign in, when an administrator already exists", async () => {
    serve({ "GET /api/setup/status": { body: { state: "complete" } } });
    render(<Setup />);
    expect(await screen.findByRole("heading", { name: "Setup has already been completed" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to sign-in" }).getAttribute("href")).toBe("/login");
  });
});

describe("the setup form", () => {
  const open = async (options: SetupOptions = OPTIONS, extra: Record<string, Reply | (() => Reply)> = {}) => {
    const calls = serve({ "GET /api/setup/status": { body: { state: "form" } }, "GET /api/setup/options": { body: options }, ...extra });
    render(<Setup />);
    await screen.findByRole("heading", { name: "Set up Northstar" });
    return calls;
  };

  it("starts with the name and email empty, no currency chosen, and the stored format and time zone", async () => {
    await open();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Household reporting currency") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Default number and date format") as HTMLSelectElement).value).toBe("en-US");
    expect((screen.getByLabelText("Time zone") as HTMLInputElement).value).toBe("UTC");
    expect(screen.getByText("Choose carefully. This cannot be changed after setup.")).toBeTruthy();
    expect(screen.queryByLabelText("Role")).toBeNull(); // the account is always an administrator
  });

  it("shows an example in the chosen number and date format, and changes it with the choice", async () => {
    await open();
    expect(screen.getByText("1,234.56 · Nov 7, 2026")).toBeTruthy();
    field("Default number and date format", "de-DE");
    expect(screen.getByText("1.234,56 · 07.11.2026")).toBeTruthy();
  });

  it("shows and hides the password", async () => {
    await open();
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(password.type).toBe("text");
    expect((screen.getByLabelText("Confirm password") as HTMLInputElement).type).toBe("text");
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(password.type).toBe("password");
  });

  it("does not send a password that does not match its confirmation", async () => {
    const calls = await open();
    fillAccount("synthetic-pass-123", "synthetic-pass-124");
    fireEvent.click(submitButton());
    expect((await screen.findByRole("alert")).textContent).toBe("The passwords don't match.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("sends what was entered, with the currency found by its name, and goes to sign-in without signing anyone in", async () => {
    const calls = await open(OPTIONS, { "POST /api/setup": { body: { email: "alex@example.com" } } });
    fillAccount();
    field("Household reporting currency", "euro");
    field("Default number and date format", "de-DE");
    field("Time zone", "America/Chicago");
    fireEvent.click(submitButton());
    await waitFor(() => expect(assign).toHaveBeenCalledWith(SETUP_COMPLETE_PATH));
    expect(calls.find((c) => c.method === "POST" && c.url === "/api/setup")!.body).toEqual({
      email: "alex@example.com", display_name: "Alex Morgan", password: "synthetic-pass-123", currency: "EUR", locale: "de-DE",
      timezone: "America/Chicago",
    });
    expect(sessionStorage.getItem(SETUP_EMAIL_KEY)).toBe("alex@example.com");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("synthetic-pass-123");
  });

  it("shows each refused field beside it, keeps what was typed and stays on the form", async () => {
    await open(OPTIONS, {
      "POST /api/setup": { status: 422, body: { detail: "Choose the household reporting currency.",
        errors: { currency: "Choose the household reporting currency.", email: "A user with that email already exists." } } },
    });
    fillAccount();
    fireEvent.click(submitButton());
    expect((await screen.findByText("A user with that email already exists.")).getAttribute("role")).toBe("alert");
    expect(screen.getAllByText("Choose the household reporting currency.").length).toBe(1);
    expect(screen.getByLabelText("Email").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("Email")); // the first field to fix
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe("Alex Morgan");
    expect(assign).not.toHaveBeenCalled();
  });

  it("asks for the token again when the setup session ends, keeping the typed fields and never the passwords", async () => {
    let session = "ended";
    await open(OPTIONS, {
      "POST /api/setup": () => (session === "ended" ? { status: 401, body: { detail: "Your setup session has ended. Enter the setup token again." } } : { body: { email: "alex@example.com" } }),
      "POST /api/setup/token": { status: 204 },
    });
    fillAccount();
    field("Household reporting currency", "USD");
    fireEvent.click(submitButton());
    expect((await screen.findByRole("status")).textContent).toContain("Your setup session ended");
    expect(screen.getByRole("heading", { name: "Welcome to Northstar" })).toBeTruthy();
    field("Setup token", "a-new-token");
    fireEvent.click(screen.getByRole("button", { name: "Continue to setup" }));
    await screen.findByRole("heading", { name: "Set up Northstar" });
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe("Alex Morgan");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("alex@example.com");
    expect((screen.getByLabelText("Household reporting currency") as HTMLInputElement).value).toBe("USD");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Confirm password") as HTMLInputElement).value).toBe("");
    session = "valid";
  });

  it("points to sign-in when setup was completed from another browser first", async () => {
    await open(OPTIONS, { "POST /api/setup": { status: 409, body: { detail: "Setup has already been completed." } } });
    fillAccount();
    field("Household reporting currency", "USD");
    fireEvent.click(submitButton());
    expect(await screen.findByRole("heading", { name: "Setup has already been completed" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to sign-in" })).toBeTruthy();
  });

  it("shows an existing locked currency read-only and does not send one", async () => {
    const calls = await open({ ...OPTIONS, currency: { value: "EUR", locked: true } }, { "POST /api/setup": { body: { email: "alex@example.com" } } });
    const currency = screen.getByLabelText("Household reporting currency") as HTMLInputElement;
    expect(currency.readOnly).toBe(true);
    expect(currency.value).toBe("EUR · Euro");
    fillAccount();
    fireEvent.click(submitButton());
    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "POST" && c.url === "/api/setup")!.body.currency).toBeNull();
  });
});

describe("the currency search and the time zone choice", () => {
  const open = async () => {
    serve({ "GET /api/setup/status": { body: { state: "form" } }, "GET /api/setup/options": { body: OPTIONS } });
    render(<Setup />);
    await screen.findByRole("heading", { name: "Set up Northstar" });
  };
  const listed = () => screen.queryByRole("listbox")?.querySelectorAll("[role=option]") ?? [];
  const names = () => [...listed()].map((o) => o.textContent);

  it("lists every currency when opened, filters by what is typed, and chooses by click", async () => {
    await open();
    const box = screen.getByLabelText("Household reporting currency");
    fireEvent.focus(box);
    expect(names()).toEqual(["USD US Dollar", "EUR Euro"]);
    fireEvent.change(box, { target: { value: "eur" } });
    expect(names()).toEqual(["EUR Euro"]);
    fireEvent.mouseDown(listed()[0]);
    expect((box as HTMLInputElement).value).toBe("EUR");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("shows all currencies again after one was chosen, instead of only the chosen one", async () => {
    await open();
    const box = screen.getByLabelText("Household reporting currency");
    fireEvent.change(box, { target: { value: "USD" } });
    fireEvent.mouseDown(listed()[0]);
    fireEvent.focus(box);
    fireEvent.click(box);
    expect(names().length).toBe(2);
  });

  it("is used from the keyboard: arrows move, Enter chooses without submitting, Escape closes", async () => {
    const calls = serve({ "GET /api/setup/status": { body: { state: "form" } }, "GET /api/setup/options": { body: OPTIONS } });
    render(<Setup />);
    await screen.findByRole("heading", { name: "Set up Northstar" });
    const box = screen.getByLabelText("Household reporting currency") as HTMLInputElement;
    fireEvent.focus(box);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(box.getAttribute("aria-activedescendant")).toBe("setup-currency-EUR");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe("EUR");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("says so when nothing matches", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Household reporting currency"), { target: { value: "zzz" } });
    expect(screen.getByText("No currency matches.")).toBeTruthy();
  });

  it("offers every time zone in a styled select, grouped by region, whatever is selected", async () => {
    await open();
    const zone = screen.getByLabelText("Time zone") as HTMLSelectElement;
    expect(zone.tagName).toBe("SELECT");
    expect([...zone.querySelectorAll("optgroup")].map((g) => g.label)).toEqual(["America", "Etc", "Europe", "Other"]);
    expect(zone.options.length).toBe(4);
    expect(zone.value).toBe("UTC");
  });

  it("groups zone names, puts those with no region last, and keeps a current value the list lacks", () => {
    expect(zoneGroups(["UTC", "Europe/Paris", "America/Chicago"], "UTC").map(([g]) => g)).toEqual(["America", "Europe", "Other"]);
    expect(zoneGroups(["Europe/Paris"], "Mars/Base").map(([g]) => g)).toEqual(["Europe", "Mars"]);
  });
});

describe("finding a currency by what was typed", () => {
  it("accepts its code or its name in any case, and passes anything else on for the server to refuse", () => {
    expect(currencyCode("usd", OPTIONS.currencies)).toBe("USD");
    expect(currencyCode(" Euro ", OPTIONS.currencies)).toBe("EUR");
    expect(currencyCode("Doubloons", OPTIONS.currencies)).toBe("Doubloons");
    expect(currencyCode("", OPTIONS.currencies)).toBe("");
  });
});

describe("the app", () => {
  it("shows the setup page at /setup without asking who is signed in", async () => {
    const calls = serve({ "GET /api/setup/status": { body: { state: "complete" } } });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Setup has already been completed" })).toBeTruthy();
    expect(calls.some((c) => c.url === "/api/me")).toBe(false);
  });
});

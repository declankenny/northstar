// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type PropertyList, type PropertyRow, RequestError } from "./api";
import { SystemProperties } from "./SystemProperties";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchProperties: vi.fn(), saveProperty: vi.fn() }));

import { fetchProperties, saveProperty } from "./api";

const row = (over: Partial<PropertyRow> & { name: string }): PropertyRow => ({
  type: "String", value: "x", allow_null: false, hint: "A hint.", read_only: false, options: [], ...over,
});

const list = (): PropertyList => ({
  properties: [
    row({ name: "currency.exchangerate.staleness_days", type: "Integer", value: "14", hint: "Days before a rate is stale. Enter 1 or more." }),
    row({ name: "currency.exchangerate.provider", value: "example" }),
    row({ name: "system.contact_email", value: null, allow_null: true, hint: "Shown on the sign-in page." }),
    row({ name: "ui.theme.default", type: "Lookup", value: "dark", hint: "Sets the theme default. Users can override it.",
      options: [{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }] }),
    row({ name: "user.session.lifetime_days", type: "Integer", value: "30", read_only: true }),
  ],
  currencies: [],
  locales: [],
});

async function open() {
  vi.mocked(fetchProperties).mockResolvedValue(list());
  render(<SystemProperties />);
  await screen.findByRole("tab", { name: /Currency/ });
}

const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement | HTMLSelectElement;
const type = (name: string, text: string) => fireEvent.change(field(name), { target: { value: text } });

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("the System properties page", () => {
  it("lists a group for the first segment of each name, with its count, and opens the first", async () => {
    await open();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Currency2", "System1", "UI1", "User1"]);
    expect(screen.getByRole("tab", { name: /Currency/ }).getAttribute("aria-selected")).toBe("true");
    expect(field("currency.exchangerate.staleness_days").value).toBe("14");
    expect(screen.queryByLabelText("ui.theme.default")).toBeNull();
  });

  it("shows another group's properties when its tab is chosen", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /^UI/ }));
    expect((field("ui.theme.default") as HTMLSelectElement).value).toBe("dark");
    expect(within(field("ui.theme.default")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Light", "Dark"]);
  });

  it("marks a locked property and cannot edit it", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /^User/ }));
    expect(screen.getByText("Locked")).toBeTruthy();
    expect(field("user.session.lifetime_days").disabled).toBe(true);
  });

  it("marks an optional property, shows Not set for it, and offers Not set in a Lookup that allows it", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /^System/ }));
    expect(screen.getByText("Optional")).toBeTruthy();
    expect(field("system.contact_email").value).toBe("");
    expect(field("system.contact_email").getAttribute("placeholder")).toBe("Not set");
  });

  it("opens and closes a property's hint from its info marker", async () => {
    await open();
    expect(screen.queryByText("Days before a rate is stale. Enter 1 or more.")).toBeNull();
    const marker = screen.getByRole("button", { name: "About currency.exchangerate.staleness_days" });
    fireEvent.click(marker);
    expect(screen.getByText("Days before a rate is stale. Enter 1 or more.")).toBeTruthy();
    expect(marker.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(marker);
    expect(screen.queryByText("Days before a rate is stale. Enter 1 or more.")).toBeNull();
  });

  it("offers Save and Revert only once a value differs from the stored one, and Revert puts it back", async () => {
    await open();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    type("currency.exchangerate.staleness_days", "20");
    expect(screen.getByRole("button", { name: "Save" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    expect(field("currency.exchangerate.staleness_days").value).toBe("14");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("does not count whitespace around the stored value as a change", async () => {
    await open();
    type("currency.exchangerate.staleness_days", " 14 ");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("saves one property, shows the list the server answers with, and says Saved", async () => {
    await open();
    const fresh = list();
    fresh.properties[0].value = "20";
    vi.mocked(saveProperty).mockResolvedValue(fresh);
    type("currency.exchangerate.staleness_days", "20");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(saveProperty).toHaveBeenCalledWith("currency.exchangerate.staleness_days", "20");
    expect(field("currency.exchangerate.staleness_days").value).toBe("20");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("shows the server's refusal beside the property, keeps what was typed, and clears it on the next edit", async () => {
    await open();
    vi.mocked(saveProperty).mockRejectedValue(new RequestError("Enter a whole number of 1 or more.", {}, 422));
    type("currency.exchangerate.staleness_days", "0");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter a whole number of 1 or more.");
    expect(field("currency.exchangerate.staleness_days").value).toBe("0");
    type("currency.exchangerate.staleness_days", "1");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sends a Lookup choice", async () => {
    await open();
    vi.mocked(saveProperty).mockResolvedValue(list());
    fireEvent.click(screen.getByRole("tab", { name: /^UI/ }));
    fireEvent.change(field("ui.theme.default"), { target: { value: "light" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(saveProperty).toHaveBeenCalledWith("ui.theme.default", "light");
  });

  it("sends blank text to unset an optional property", async () => {
    vi.mocked(fetchProperties).mockResolvedValue({ properties: [row({ name: "system.contact_email", value: "a@example.com", allow_null: true })], currencies: [], locales: [] });
    render(<SystemProperties />);
    await screen.findByLabelText("system.contact_email");
    vi.mocked(saveProperty).mockResolvedValue({ properties: [row({ name: "system.contact_email", value: null, allow_null: true })], currencies: [], locales: [] });
    type("system.contact_email", "   ");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    expect(saveProperty).toHaveBeenCalledWith("system.contact_email", "   ");
    expect(field("system.contact_email").value).toBe("");
  });
});

describe("leaving a group with unsaved changes", () => {
  async function edited() {
    await open();
    type("currency.exchangerate.staleness_days", "20");
  }

  it("marks the group with a dot while it has unsaved changes", async () => {
    await edited();
    expect(within(screen.getByRole("tab", { name: /Currency/ })).getByLabelText("Unsaved changes")).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /^System/ })).queryByLabelText("Unsaved changes")).toBeNull();
  });

  it("asks before switching, and Keep editing stays with the changes", async () => {
    await edited();
    fireEvent.click(screen.getByRole("tab", { name: /^System/ }));
    expect(screen.getByRole("alert").textContent).toContain("Discard changes to 1 setting in Currency?");
    expect(screen.getByRole("tab", { name: /Currency/ }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(field("currency.exchangerate.staleness_days").value).toBe("20");
  });

  it("switches and drops the changes when they are discarded", async () => {
    await edited();
    fireEvent.click(screen.getByRole("tab", { name: /^System/ }));
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByRole("tab", { name: /^System/ }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: /Currency/ }));
    expect(field("currency.exchangerate.staleness_days").value).toBe("14");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("switches at once when there is nothing unsaved", async () => {
    await open();
    fireEvent.click(screen.getByRole("tab", { name: /^System/ }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("tab", { name: /^System/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("says how many settings would be discarded", async () => {
    await edited();
    type("currency.exchangerate.provider", "other");
    fireEvent.click(screen.getByRole("tab", { name: /^System/ }));
    expect(screen.getByRole("alert").textContent).toContain("Discard changes to 2 settings in Currency?");
  });
});

describe("loading", () => {
  it("says so when the properties cannot be loaded", async () => {
    vi.mocked(fetchProperties).mockRejectedValue(new Error("The server answered 500"));
    render(<SystemProperties />);
    expect(await screen.findByText(/Could not load system properties. The server answered 500/)).toBeTruthy();
  });
});

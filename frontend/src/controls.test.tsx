// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type AccountList, type AccountPage, type Me, RequestError, type UpdatePage } from "./api";
import { AddAccountDialog, BalanceDialog } from "./AccountDialogs";
import { AmountReading } from "./AmountReading";
import { type Locale, setLocale, US_ENGLISH } from "./locale";
import { currencyMark, readAmount, setCurrency } from "./money";
import { Profile } from "./Profile";
import { RefreshMe } from "./session";
import { UpdateBalances } from "./UpdateBalances";
import { Users } from "./Users";
import vectors from "./testdata/locale_vectors.json";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchLocales: vi.fn(), updateMe: vi.fn(), fetchUsers: vi.fn(), addUser: vi.fn(), fetchUpdate: vi.fn(), saveUpdate: vi.fn(),
}));

import { addUser, fetchLocales, fetchUpdate, fetchUsers, saveUpdate, updateMe } from "./api";

const conventions = vectors.locales as Record<string, Omit<Locale, "tag" | "label">>;
const locale = (tag: string, label = tag): Locale => ({ tag, label, ...conventions[tag] } as Locale);
const GERMAN = locale("de-DE", "German (Germany)");

const CHOICES = {
  locales: [
    { tag: "en-US", label: "English (United States)" },
    { tag: "de-DE", label: "German (Germany)" },
    { tag: "fr-FR", label: "French (France)" },
  ],
  default: "de-DE",
};

const me = (over: Partial<Me> = {}): Me => ({
  id: 1, email: "test@example.com", display_name: "Test Admin", is_admin: true, theme: "dark", has_password: true, currency: null,
  locale: { ...US_ENGLISH }, ...over,
});

beforeEach(() => {
  vi.mocked(fetchLocales).mockResolvedValue(CHOICES);
});
afterEach(() => {
  cleanup();
  setLocale(null);
  setCurrency(null);
  vi.resetAllMocks();
});

// -- reading what is typed --

describe("how typed text is read", () => {
  it.each(vectors.parse_refused)("says why $locale $units places $text cannot be read", (v) => {
    setLocale(locale(v.locale));
    setCurrency({ code: "EUR", name: "Euro", minor_units: v.units });
    const reading = readAmount(v.text);
    if (v.text.trim() === "") return expect(reading).toBeNull();
    expect(reading && "message" in reading ? reading.message : "no message").toContain(v.says);
  });

  it.each(vectors.parse_ok)("reads $locale $units places $text", (v) => {
    setLocale(locale(v.locale));
    setCurrency({ code: "EUR", name: "Euro", minor_units: v.units });
    expect(readAmount(v.text)).toEqual({ cents: v.minor });
  });

  it("says nothing until something is typed", () => {
    expect(readAmount("")).toBeNull();
    expect(readAmount("   ")).toBeNull();
  });

  it("marks the amount box with a dollar sign only for US dollars in US English", () => {
    expect(currencyMark()).toBe("$");
    setLocale(GERMAN);
    expect(currencyMark()).toBe("USD");
    setLocale(null);
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    expect(currencyMark()).toBe("EUR");
  });

  it("shows the line under a box: empty, then what it reads as, then why it cannot be read", () => {
    setLocale(GERMAN);
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    const { container, rerender } = render(<AmountReading text="" />);
    expect(container.textContent).toBe("");
    rerender(<AmountReading text="1.234,56" />);
    expect(container.textContent).toBe("Reads as 1.234,56\u00a0EUR");
    expect(container.querySelector(".reads.ok")).toBeTruthy();
    rerender(<AmountReading text="12.50" />);
    expect(container.textContent).toContain("Use , for decimals");
    expect(container.querySelector(".reads.bad")).toBeTruthy();
    expect(container.querySelector("[aria-live=polite]")).toBeTruthy();
  });
});

// -- the profile --

describe("the profile's number and date format", () => {
  it("is a dropdown of the catalog's labels, set to the current format", async () => {
    render(<Profile me={me()} onChange={vi.fn()} onTheme={vi.fn()} />);
    const select = (await screen.findByLabelText("Number and date format")) as HTMLSelectElement;
    await waitFor(() => expect([...select.options].map((o) => o.textContent)).toEqual(
      ["English (United States)", "German (Germany)", "French (France)"]));
    expect(select.value).toBe("en-US");
  });

  it("saves as soon as a format is chosen, with no Save button, and hands the updated account to the app", async () => {
    const updated = me({ locale: { ...GERMAN } });
    vi.mocked(updateMe).mockResolvedValue(updated);
    const onChange = vi.fn();
    render(<Profile me={me()} onChange={onChange} onTheme={vi.fn()} />);
    const select = await screen.findByLabelText("Number and date format");
    await waitFor(() => expect((select as HTMLSelectElement).options.length).toBe(3));
    fireEvent.change(select, { target: { value: "de-DE" } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated));
    expect(updateMe).toHaveBeenCalledWith({ locale: "de-DE" });
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("shows the refusal and leaves the app as it was", async () => {
    vi.mocked(updateMe).mockRejectedValue(new Error("Choose a number and date format from the list."));
    const onChange = vi.fn();
    render(<Profile me={me()} onChange={onChange} onTheme={vi.fn()} />);
    const select = await screen.findByLabelText("Number and date format");
    await waitFor(() => expect((select as HTMLSelectElement).options.length).toBe(3));
    fireEvent.change(select, { target: { value: "fr-FR" } });
    expect((await screen.findByRole("alert")).textContent).toBe("Choose a number and date format from the list.");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("works before the catalog has loaded, showing the current format", () => {
    vi.mocked(fetchLocales).mockReturnValue(new Promise(() => {}));
    render(<Profile me={me({ locale: { ...GERMAN } })} onChange={vi.fn()} onTheme={vi.fn()} />);
    const select = screen.getByLabelText("Number and date format") as HTMLSelectElement;
    expect([select.value, select.options.length]).toEqual(["de-DE", 1]);
  });
});

// -- the admin's new-user form --

describe("the new-user form's number and date format", () => {
  const added = { id: 9, email: "new@example.com", display_name: "Test New", is_admin: false, created_at: "2026-11-05", reactivated: false, sign_in: "local" as const };
  const fill = () => {
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Test New" } });
    fireEvent.change(screen.getByLabelText("Starting password"), { target: { value: "synthetic-pass-123" } });
  };

  beforeEach(() => {
    vi.mocked(fetchUsers).mockResolvedValue([]);
    vi.mocked(addUser).mockResolvedValue(added);
  });

  it("starts at the system default", async () => {
    render(<Users me={me()} onMe={vi.fn()} />);
    const select = (await screen.findByLabelText("Number and date format")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("de-DE"));
  });

  it("adds the user in the default, or in the format that was chosen, and then goes back to the default", async () => {
    render(<Users me={me()} onMe={vi.fn()} />);
    const select = (await screen.findByLabelText("Number and date format")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("de-DE"));
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(addUser).toHaveBeenCalledTimes(1));
    expect(vi.mocked(addUser).mock.calls[0][0]).toMatchObject({ email: "new@example.com", locale: "de-DE" });

    fireEvent.change(select, { target: { value: "fr-FR" } });
    expect(select.value).toBe("fr-FR");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(addUser).toHaveBeenCalledTimes(2));
    expect(vi.mocked(addUser).mock.calls[1][0]).toMatchObject({ locale: "fr-FR" });
    await waitFor(() => expect(select.value).toBe("de-DE"));      // the next user starts from the default again
  });
});

// -- amount boxes and the refusal when the format changed --

const list = (): AccountList => ({
  currency: { code: "EUR", name: "Euro", minor_units: 2 }, currencies: [{ code: "EUR", name: "Euro", minor_units: 2 }], closed: false, accounts: [], totals: { assets: 0, liabilities: 0 }, today: "2026-11-05",
  classes: [{ id: 1, name: "Asset", types: [{ id: 1, name: "Savings" }] }, { id: 2, name: "Liability", types: [] }],
});

const changed = () => new RequestError("Your number and date format changed to German (Germany). Nothing was saved.", {}, 409, [], null, [],
  { tag: "de-DE", label: "German (Germany)" });

describe("the Add account dialog", () => {
  const open = (onSave = vi.fn().mockResolvedValue(undefined), refresh = vi.fn()) => {
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    render(
      <RefreshMe.Provider value={refresh}>
        <AddAccountDialog list={list()} isAdmin accountClass="asset" onSave={onSave} onClose={vi.fn()} />
      </RefreshMe.Provider>,
    );
    return { onSave, refresh };
  };

  it("says how the balance reads, in the person's format, only once something is typed", () => {
    setLocale(GERMAN);
    open();
    const reading = () => document.querySelector(".reads")!.textContent;
    expect(reading()).toBe("");
    fireEvent.change(screen.getByLabelText(/Current balance/), { target: { value: "1.234,56" } });
    expect(reading()).toBe("Reads as 1.234,56\u00a0EUR");
    fireEvent.change(screen.getByLabelText(/Current balance/), { target: { value: "12.50" } });
    expect(reading()).toContain("Use , for decimals");
  });

  it("keeps the draft, says the format changed and asks the app to load it, when the save is refused for that", async () => {
    const { onSave, refresh } = open(vi.fn().mockRejectedValue(changed()));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test Sparkonto" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/Current balance/), { target: { value: "1,234.56" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Your number and date format changed to German (Germany). Nothing was saved.");
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Test Sparkonto");
    expect((screen.getByLabelText(/Current balance/) as HTMLInputElement).value).toBe("1,234.56");
  });

  it("does not ask the app to load anything for an ordinary refusal", async () => {
    const { refresh } = open(vi.fn().mockRejectedValue(new Error("A name is needed.")));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await screen.findByRole("alert");
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("the balance dialog", () => {
  const account = { id: 7, name: "Test savings", today: "2026-11-05" } as AccountPage;

  it("says how the balance reads, as it is typed, and starts an edit in the format of the person", () => {
    setLocale(GERMAN);
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    render(<BalanceDialog account={account} editing={{ id: 1, as_of_date: "2026-10-31", amount_cents: 123456, note: null, version: 3 }}
      onSave={vi.fn()} onClose={vi.fn()} />);
    const box = screen.getByLabelText("Balance") as HTMLInputElement;
    expect(box.value).toBe("1234,56");                                              // the locale's decimal mark, no grouping
    expect(document.querySelector(".reads")!.textContent).toBe("Reads as 1.234,56\u00a0EUR");
    fireEvent.change(box, { target: { value: "1,234.56" } });
    expect(document.querySelector(".reads")!.textContent).toContain("Enter an amount like 1234,56");
    expect(box.placeholder).toBe("0,00");
  });
});

// -- the Update balances screen --

const row = (id: number, name: string, over = {}) => ({
  id, name, currency: { code: "EUR", name: "Euro", minor_units: 2 }, class_name: "Asset", type_name: "Savings", stale_after_days: 35, last_date: "2026-10-31", last_cents: 100000,
  days_since: 5, stale: false, existing_cents: null, existing_version: null, ...over,
});
const page = (rows = [row(1, "Test checking"), row(2, "Test savings", { existing_cents: 123456, existing_version: 4 })]): UpdatePage => ({
  date: "2026-11-05", today: "2026-11-05", rows, saved: null,
} as UpdatePage);

describe("the Update balances screen", () => {
  const open = async (refresh = vi.fn()) => {
    setCurrency({ code: "EUR", name: "Euro", minor_units: 2 });
    vi.mocked(fetchUpdate).mockResolvedValue(page());
    const view = render(<RefreshMe.Provider value={refresh}><UpdateBalances /></RefreshMe.Provider>);
    await screen.findByLabelText("New balance for Test checking");
    return { ...view, refresh };
  };

  it("says how each typed amount reads, in the person's format and the account's currency, and marks the box with the currency", async () => {
    setLocale(GERMAN);
    await open();
    expect(document.querySelectorAll(".ub-in.code i")[0].textContent).toBe("EUR");
    fireEvent.change(screen.getByLabelText("New balance for Test checking"), { target: { value: "2.000,5" } });
    const lines = () => [...document.querySelectorAll(".reads")].map((e) => e.textContent);
    expect(lines()[0]).toBe("Reads as 2.000,50\u00a0EUR");
    fireEvent.change(screen.getByLabelText("New balance for Test checking"), { target: { value: "2.000.5" } });
    expect(lines()[0]).toContain("Use , for decimals");
  });

  it("starts the box of a saved balance in the person's format", async () => {
    setLocale(GERMAN);
    await open();
    expect((screen.getByLabelText("New balance for Test savings") as HTMLInputElement).value).toBe("1234,56");
  });

  it("shows no dollar sign for euros", async () => {
    await open();
    expect(document.querySelector(".ub-in i")!.textContent).toBe("EUR");
  });

  it("refuses a save made in a format that has changed, keeps what was typed and asks the app to load the new one", async () => {
    vi.mocked(saveUpdate).mockRejectedValue(changed());
    const { refresh } = await open();
    fireEvent.change(screen.getByLabelText("New balance for Test checking"), { target: { value: "2,000.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    expect((await screen.findByText("Your number and date format changed to German (Germany). Nothing was saved.")).textContent).toBeTruthy();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("New balance for Test checking") as HTMLInputElement).value).toBe("2,000.50");
  });

  it("writes the boxes that still hold what was loaded in the new format when the format changes, and leaves what was typed", async () => {
    const { rerender, refresh } = await open();
    fireEvent.change(screen.getByLabelText("New balance for Test checking"), { target: { value: "2,000.50" } });
    expect((screen.getByLabelText("New balance for Test savings") as HTMLInputElement).value).toBe("1234.56");
    setLocale(GERMAN);                                                               // the app loaded the new format
    rerender(<RefreshMe.Provider value={refresh}><UpdateBalances /></RefreshMe.Provider>);
    await waitFor(() => expect((screen.getByLabelText("New balance for Test savings") as HTMLInputElement).value).toBe("1234,56"));
    expect((screen.getByLabelText("New balance for Test checking") as HTMLInputElement).value).toBe("2,000.50");
  });

  it("sends the format the page was using with a save", async () => {
    vi.mocked(saveUpdate).mockResolvedValue({ ...page(), saved: { added: 1, updated: 0, unchanged: 0 } });
    setLocale(GERMAN);
    await open();
    fireEvent.change(screen.getByLabelText("New balance for Test checking"), { target: { value: "2.000,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balances" }));
    await waitFor(() => expect(saveUpdate).toHaveBeenCalled());
    expect(vi.mocked(saveUpdate).mock.calls[0][1]).toEqual({ 1: "2.000,5" });
  });
});

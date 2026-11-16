// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage as Account, ListColumn, ListPage } from "./api";
import { AccountPage } from "./AccountPage";
import { AccountsList } from "./AccountsList";
import { clearFlash } from "./flash";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchAccount: vi.fn(), fetchNetWorth: vi.fn(), editAccount: vi.fn(), fetchAccountOptions: vi.fn(), fetchList: vi.fn(), fetchListFields: vi.fn(),
}));

import { editAccount, fetchAccount, fetchAccountOptions, fetchList, fetchListFields } from "./api";

const account = (over: Partial<Account> = {}): Account => ({
  id: 7, name: "Visa Card", currency: { code: "USD", name: "US Dollar", minor_units: 2 }, class_name: "Liability", type_id: 4, type_name: "Credit card", is_open: true,
  notes: null, website: null, website_removed: [], due_day: null, next_due: null, stale_after_days: 30, balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null, stale: false,
  types: [{ id: 4, name: "Credit card" }], other_class: { id: 1, name: "Asset", types: [] }, today: "2026-11-15", ...over,
});

beforeEach(() => window.history.replaceState(null, "", "/accounts/7"));
afterEach(() => {
  cleanup();
  clearFlash();
  vi.resetAllMocks();
});

const openEdit = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "More actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Edit account" }));
  return await screen.findByRole("dialog");
};

describe("the website on the account page", () => {
  it("is a link showing the site's name, which opens in a new tab and is named by what is on screen", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ website: "https://www.bank.example/pay" }));
    render(<AccountPage id={7} isAdmin />);
    const link = await screen.findByRole("link", { name: "bank.example — Open Visa Card's website (opens in a new tab)" });
    expect(link.getAttribute("href")).toBe("https://www.bank.example/pay");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.textContent).toContain("bank.example");
  });

  it("is not shown when the account has none", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    render(<AccountPage id={7} isAdmin />);
    await screen.findByRole("heading", { name: "Visa Card" });
    expect(screen.queryByRole("link", { name: /Open Visa Card's website/ })).toBeNull();
  });

  it("is edited in the Edit account dialog, and what is typed is sent as typed", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ website: "https://www.bank.example/" }));
    vi.mocked(editAccount).mockResolvedValue(account({ website: "https://other.example/" }));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    const box = within(dialog).getByLabelText("Website (optional)") as HTMLInputElement;
    expect(box.value).toBe("https://www.bank.example/");
    fireEvent.change(box, { target: { value: "  https://other.example/  " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(editAccount).toHaveBeenCalledWith(7, { name: "Visa Card", type_id: 4, notes: "", website: "  https://other.example/  ", due_day: null }));
    expect((await screen.findByRole("link", { name: /other\.example/ })).getAttribute("href")).toBe("https://other.example/");
    expect(screen.queryByRole("status")).toBeNull();                      // nothing was removed, so nothing is said
  });

  it("says what saving removed, in a notice that goes when something else is done", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    vi.mocked(editAccount)
      .mockResolvedValueOnce(account({ website: "https://bank.example/x", website_removed: ["query"] }))
      .mockResolvedValueOnce(account({ website: "https://bank.example/x" }));
    render(<AccountPage id={7} isAdmin />);
    let dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText("Website (optional)"), { target: { value: "https://bank.example/x?token=1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("status")).textContent).toBe("Saved. The website was saved without the part after “?”, which can carry a sign-in token.");
    dialog = await openEdit();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("shows a refusal in the dialog and keeps it open", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account());
    vi.mocked(editAccount).mockRejectedValue(new Error("Enter a full web address starting with http:// or https://, such as https://www.bank.example/."));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    fireEvent.change(within(dialog).getByLabelText("Website (optional)"), { target: { value: "bank.example" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Enter a full web address");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("has no hint beside the field (an asset has no other hint in the dialog): what is removed is said after saving", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ class_name: "Asset" }));
    render(<AccountPage id={7} isAdmin />);
    const dialog = await openEdit();
    expect(dialog.querySelectorAll(".hint").length).toBe(0);
  });
});

describe("the Website column of the Accounts list", () => {
  const column = (key: string, label: string): ListColumn => ({ key, label, path_label: label, kind: "text", scale: null, linked: key === "name", groupable: true });
  const listPage = (columns: ListColumn[], rows: ListPage["rows"]): ListPage => ({
    columns, total: rows.length, page: 1, pages: 1, page_size: 25, group: null, sort: { field: "name", direction: "asc" }, filters: [], skipped: [],
    default_filter_id: null, default_columns: ["name"], customised: true, skipped_columns: [], rows,
  });
  const show = async (page: ListPage) => {
    window.history.replaceState(null, "", "/accounts");
    vi.mocked(fetchAccountOptions).mockResolvedValue({ currency: { code: "USD", name: "US Dollar", minor_units: 2 }, currencies: [], today: "2026-11-15", classes: [] });
    vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
    vi.mocked(fetchList).mockResolvedValue(page);
    render(<AccountsList isAdmin={false} />);
  };

  it("is a link to the site, named by what is on screen and the account, and a dash where there is none", async () => {
    await show(listPage([column("name", "Account"), column("website", "Website")], [
      { _id: 1, _links: { name: "/accounts/1" }, name: "Visa Card", website: "https://www.bank.example/" },
      { _id: 2, _links: { name: "/accounts/2" }, name: "Joint savings", website: null },
    ]));
    const link = await screen.findByRole("link", { name: "bank.example — Open Visa Card's website (opens in a new tab)" });
    expect(link.getAttribute("href")).toBe("https://www.bank.example/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    const dash = (await screen.findByText("Joint savings", { selector: "a" })).closest("tr")!.querySelectorAll("td")[1];
    expect(dash.textContent).toBe("—");
  });

  it("falls back to a general name when the person has taken the Name column out", async () => {
    await show(listPage([column("website", "Website")], [{ _id: 1, _links: {}, website: "https://bank.example/" }]));
    expect(await screen.findByRole("link", { name: "bank.example — Open the account's website (opens in a new tab)" })).toBeTruthy();
  });
});

// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListColumn, ListPage, ListRequest, ListRow } from "./api";
import { ListView } from "./ListView";
import { deferred } from "./testing";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn() }));

import { fetchList, saveListPageSize } from "./api";

const COLUMNS: ListColumn[] = [
  { key: "as_of_date", label: "Date", path_label: "Date", kind: "date", scale: null, linked: false },
  { key: "account", label: "Account", path_label: "Account", kind: "text", scale: null, linked: true },
  { key: "amount_cents", label: "Value", path_label: "Value", kind: "amount", scale: null, linked: false },
  { key: "note", label: "Note", path_label: "Note", kind: "text", scale: null, linked: false },
];

const row = (id: number, over: Partial<ListRow> = {}): ListRow => ({
  _id: id, as_of_date: "2026-05-31", account: `Test account ${id}`, amount_cents: { value: 123456, scale: 2, unit: "USD" }, note: null,
  _links: { account: `/accounts/${id}` }, ...over,
});

const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: [row(1), row(2)], total: 138, page: 1, pages: 14, page_size: 10, group: null,
  sort: { field: "as_of_date", direction: "desc" }, ...over,
});

const requests = () => vi.mocked(fetchList).mock.calls.map((call) => call[1] as ListRequest);
const here = () => window.location.pathname + window.location.search;
// How many entries the app has added to the history: the router numbers them, which does not stop counting the way history.length does.
const entries = () => (window.history.state as { idx?: number } | null)?.idx ?? 0;

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(saveListPageSize).mockImplementation(async (_key, size) => size);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

describe("a list", () => {
  it("shows the columns, the cells in the person's formats, the links, and an empty cell as a dash", async () => {
    render(<ListView listKey="balances" />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent?.replace(/[▾▲▼]/g, "").trim())).toEqual(["Date", "Account", "Value", "Note"]);
    const first = within(table).getAllByRole("row")[1];
    expect(within(first).getByText("May 31, 2026")).toBeTruthy();
    expect(within(first).getByRole("link", { name: "Test account 1" }).getAttribute("href")).toBe("/accounts/1");
    expect(within(first).getByText("$1,234.56")).toBeTruthy();
    expect(within(first).getByText("—")).toBeTruthy();
    expect(fetchList).toHaveBeenCalledWith("balances", { page: 1 }, expect.anything());
  });

  it("says where the page is and how many rows match", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    expect(screen.getByText("1–2 of 138")).toBeTruthy();
    expect(screen.getByText("Page 1 of 14")).toBeTruthy();
    expect(screen.getByText("138 matching")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("draws a column its own way when the list's page says so", async () => {
    render(<ListView listKey="balances" config={{ cell: { note: (r) => <em>No rate for {String(r._id)}</em> } }} />);
    expect(await screen.findAllByText(/No rate for/)).toHaveLength(2);
  });
});

describe("sorting", () => {
  it("sorts ascending on a click, reverses on a second click, and says so to a screen reader", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const header = () => screen.getByRole("columnheader", { name: /Account/ });
    expect(header().getAttribute("aria-sort")).toBe("none");

    fireEvent.click(within(header()).getByText("Account"));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, sort: { field: "account", direction: "asc" } }));
    expect(here()).toBe("/balances?sort=account");
    expect(header().getAttribute("aria-sort")).toBe("ascending");

    fireEvent.click(within(header()).getByText("Account"));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, sort: { field: "account", direction: "desc" } }));
    expect(here()).toBe("/balances?sort=-account");
    expect(header().getAttribute("aria-sort")).toBe("descending");

    fireEvent.click(within(header()).getByText("Account"));
    await waitFor(() => expect(here()).toBe("/balances?sort=account"));            // a click never removes the sort
  });

  it("shows the list's own sort before anyone chooses one, and a click on that column reverses it", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    expect(screen.getByRole("columnheader", { name: /Date/ }).getAttribute("aria-sort")).toBe("descending");
    expect(screen.getByRole("columnheader", { name: /Account/ }).getAttribute("aria-sort")).toBe("none");
    fireEvent.click(screen.getByText("Date"));
    await waitFor(() => expect(here()).toBe("/balances?sort=as_of_date"));            // from newest first to oldest first
  });

  it("starts another column ascending even when the list's own sort is ascending", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ sort: { field: "account", direction: "asc" } }));
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByText("Account"));                                    // the sort column itself: reversed
    await waitFor(() => expect(here()).toBe("/balances?sort=-account"));
  });

  it("sorts another column ascending and goes back to the first page", async () => {
    window.history.replaceState(null, "", "/balances?sort=-account&page=3");
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByText("Date"));
    await waitFor(() => expect(here()).toBe("/balances?sort=as_of_date"));
  });

  it("offers both directions in the column's menu", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Column menu for Value" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sort descending" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, sort: { field: "amount_cents", direction: "desc" } }));
    fireEvent.click(screen.getByRole("button", { name: "Column menu for Value" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sort ascending" }));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, sort: { field: "amount_cents", direction: "asc" } }));
  });

  it("closes the menu with Escape", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Column menu for Date" }));
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("the address", () => {
  it("restores the whole view from it: the sort, the page and the search", async () => {
    window.history.replaceState(null, "", "/balances?sort=-account&page=3&q=note");
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    expect(requests()[0]).toEqual({ page: 3, sort: { field: "account", direction: "desc" }, search: "note" });
    expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe("note");
  });

  it("puts each page in a history entry, so Back returns to the view before", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const before = entries();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(here()).toBe("/balances?page=2"));
    expect(entries()).toBe(before + 1);
    act(() => window.history.back());
    await waitFor(() => expect(here()).toBe("/balances"));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1 }));
  });

  it("does not add a history entry for each letter typed in the search, and asks once the typing pauses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const before = entries();
    const box = screen.getByLabelText("Search");
    for (const text of ["a", "av", "ave", "aver"]) fireEvent.change(box, { target: { value: text } });
    expect(here()).toBe("/balances");                                              // still typing: nothing asked yet
    act(() => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(here()).toBe("/balances?q=aver"));
    expect(entries()).toBe(before);                                                // the address was replaced, not added to
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, search: "aver" }));
    expect(requests().filter((r) => r.search !== undefined)).toHaveLength(1);
  });

  it("goes back to the first page when the search changes, and keeps what was typed while the answer is on its way", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", "/balances?page=4");
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const box = screen.getByLabelText("Search") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "ab" } });
    act(() => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(here()).toBe("/balances?q=ab"));
    fireEvent.change(box, { target: { value: "abc" } });                           // typed after the address changed
    expect(box.value).toBe("abc");
    act(() => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(here()).toBe("/balances?q=abc"));
  });
});

describe("paging", () => {
  it("moves to the next and previous page, and disables the buttons at either end", async () => {
    vi.mocked(fetchList).mockImplementation(async (_key, request) => page({ page: request.page ?? 1, pages: 3, total: 25 }));
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(here()).toBe("/balances?page=2"));
    await screen.findByText("Page 2 of 3");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 3 of 3");
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByText("Page 2 of 3");
  });

  it("remembers a new page size, asks for it from the first page, and shows it", async () => {
    window.history.replaceState(null, "", "/balances?page=3");
    vi.mocked(fetchList).mockImplementation(async (_key, request) => page({ page_size: request.page_size ?? 10, page: request.page ?? 1 }));
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText(/Rows per page/), { target: { value: "50" } });
    await waitFor(() => expect(saveListPageSize).toHaveBeenCalledWith("balances", 50));
    await waitFor(() => expect(requests().at(-1)).toEqual({ page: 1, page_size: 50 }));
    expect(here()).toBe("/balances");
    expect((screen.getByLabelText(/Rows per page/) as HTMLSelectElement).value).toBe("50");
  });

  it("says so when the page size could not be remembered, and still shows the list that way", async () => {
    vi.mocked(saveListPageSize).mockRejectedValue(new Error("The server answered 500"));
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText(/Rows per page/), { target: { value: "25" } });
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("could not be remembered"));
  });
});

describe("while it loads and when it cannot", () => {
  it("says it is loading, then shows the list", async () => {
    const answer = deferred<ListPage>();
    vi.mocked(fetchList).mockReturnValue(answer.promise);
    render(<ListView listKey="balances" />);
    expect(screen.getByText("Loading…")).toBeTruthy();
    await act(async () => answer.resolve(page()));
    expect(await screen.findByRole("table")).toBeTruthy();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("offers to try again when it fails, and keeps what it last showed when a later request fails", async () => {
    vi.mocked(fetchList).mockRejectedValueOnce(new Error("The server answered 500"));
    render(<ListView listKey="balances" />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The server answered 500");
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
    expect(screen.queryByRole("alert")).toBeNull();

    vi.mocked(fetchList).mockRejectedValueOnce(new Error("The server answered 502"));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect((await screen.findByRole("alert")).textContent).toContain("502");
    expect(screen.getByRole("table")).toBeTruthy();                                // the last good view is still there
    expect(screen.getByText("Test account 1")).toBeTruthy();
  });

  it("keeps the rows on screen, marked busy, while the next page loads", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const next = deferred<ListPage>();
    vi.mocked(fetchList).mockReturnValue(next.promise);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByRole("table").className).toContain("lf-busy"));
    expect(screen.getByText("Test account 1")).toBeTruthy();
    await act(async () => next.resolve(page({ page: 2, rows: [row(11)] })));
    await screen.findByText("Test account 11");
    expect(screen.getByRole("table").className).not.toContain("lf-busy");
  });

  it("shows the answer to the latest request even when an earlier one arrives after it", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    const slow = deferred<ListPage>();
    const fast = deferred<ListPage>();
    vi.mocked(fetchList).mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    fireEvent.click(screen.getByText("Account"));                                   // the first sort
    await waitFor(() => expect(requests().length).toBe(2));
    fireEvent.click(screen.getByText("Value"));                                     // the second, which should win
    await waitFor(() => expect(requests().length).toBe(3));
    await act(async () => fast.resolve(page({ rows: [row(21, { account: "Latest answer" })] })));
    await screen.findByText("Latest answer");
    await act(async () => slow.resolve(page({ rows: [row(22, { account: "Overtaken answer" })] })));
    expect(screen.queryByText("Overtaken answer")).toBeNull();
    expect(screen.getByText("Latest answer")).toBeTruthy();
  });
});

describe("when there is nothing to show", () => {
  it("says an empty list is empty, in the list's own words", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ rows: [], total: 0, pages: 1 }));
    render(<ListView listKey="balances" config={{ emptyText: "No balances yet." }} />);
    expect(await screen.findByText("No balances yet.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says nothing matches a search and clears it", async () => {
    window.history.replaceState(null, "", "/balances?q=zzz");
    vi.mocked(fetchList).mockResolvedValue(page({ rows: [], total: 0, pages: 1 }));
    render(<ListView listKey="balances" />);
    expect(await screen.findByText(/No rows match/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear the search" }));
    await waitFor(() => expect(here()).toBe("/balances"));
    await waitFor(() => expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe(""));
  });
});

describe("a row's menu", () => {
  it("is drawn from the list's own actions, with a disabled one saying why", async () => {
    const edit = vi.fn();
    render(<ListView listKey="balances" config={{
      rowLabel: (r) => String(r.account),
      actions: (r) => [{ label: "Edit", onClick: () => edit(r._id) },
        { label: "Delete", danger: true, disabled: r._id === 1, note: "the account is closed", onClick: () => {} }],
    }} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Actions for Test account 1" }));
    expect((screen.getByRole("menuitem", { name: /Delete/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/the account is closed/)).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit" }));
    expect(edit).toHaveBeenCalledWith(1);
  });

  it("has no column for actions when the list has none", async () => {
    render(<ListView listKey="balances" />);
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Actions for/ })).toBeNull();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
  });
});

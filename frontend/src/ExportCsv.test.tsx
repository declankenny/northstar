// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListColumn, ListPage, ListRow } from "./api";
import { ListView } from "./ListView";
import { deferred } from "./testing";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchList: vi.fn(), saveListPageSize: vi.fn(), fetchListFields: vi.fn(), fetchListChoices: vi.fn(),
  fetchSavedFilters: vi.fn(), exportList: vi.fn(),
}));

import { exportList, fetchList, fetchListChoices, fetchListFields, fetchSavedFilters } from "./api";

const COLUMNS: ListColumn[] = [
  { key: "as_of_date", label: "Date", path_label: "Date", kind: "date", scale: null, linked: false, groupable: true },
  { key: "note", label: "Note", path_label: "Note", kind: "text", scale: null, linked: false, groupable: true },
];
const rows = (n: number): ListRow[] => Array.from({ length: n }, (_, i) => ({ _id: i + 1, _links: {}, as_of_date: "2026-05-01", note: null }));
const page = (over: Partial<ListPage> = {}): ListPage => ({
  columns: COLUMNS, rows: rows(3), total: 131, page: 1, pages: 6, page_size: 25, group: null, sort: { field: "as_of_date", direction: "desc" },
  filters: [], skipped: [], default_filter_id: null, default_columns: ["as_of_date", "note"], customised: false, skipped_columns: [], ...over,
});

beforeEach(() => {
  window.history.replaceState(null, "", "/balances");
  vi.mocked(fetchList).mockResolvedValue(page());
  vi.mocked(fetchListFields).mockResolvedValue({ fields: [], relations: [] });
  vi.mocked(fetchListChoices).mockResolvedValue({ kind: "values", values: [], more: false, options: [] });
  vi.mocked(fetchSavedFilters).mockResolvedValue({ filters: [], default_id: null });
  vi.mocked(exportList).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const button = () => screen.findByRole("button", { name: /Export CSV|Exporting/ }) as Promise<HTMLButtonElement>;

describe("the Export CSV button", () => {
  it("is in the footer to the right of Previous and Next, with how many rows the file will have beside it", async () => {
    render(<ListView listKey="balances" />);
    const export_ = await button();
    const foot = export_.closest(".lf-foot")!;
    const order = [...foot.querySelectorAll("button")].map((b) => b.textContent);
    expect(order.slice(0, 3)).toEqual(["Previous", "Next", "Export CSV"]);
    expect(export_.nextElementSibling?.textContent).toBe("131 rows");
    expect(export_.disabled).toBe(false);
  });

  it("says one row in the singular", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ total: 1, pages: 1, rows: rows(1) }));
    render(<ListView listKey="balances" />);
    expect((await button()).nextElementSibling?.textContent).toBe("1 row");
  });

  it("asks for the list's own view, as the address says it, and not a page of it", async () => {
    window.history.replaceState(null, "", `/balances?sort=-note&q=rent&group=note&page=3&filters=${encodeURIComponent(JSON.stringify([{ field: "note", operator: "contains", value: "x" }]))}`);
    render(<ListView listKey="balances" />);
    fireEvent.click(await button());
    await waitFor(() => expect(exportList).toHaveBeenCalledTimes(1));
    const [key, request] = vi.mocked(exportList).mock.calls[0];
    expect(key).toBe("balances");
    expect(request).toMatchObject({ sort: { field: "note", direction: "desc" }, search: "rent", group: "note", filters: [{ field: "note", operator: "contains", value: "x" }] });
  });

  it("names no columns and no filters when the person has changed neither, so the server uses theirs", async () => {
    render(<ListView listKey="balances" />);
    fireEvent.click(await button());
    await waitFor(() => expect(exportList).toHaveBeenCalled());
    const request = vi.mocked(exportList).mock.calls[0][1];
    expect("columns" in request).toBe(false);
    expect("filters" in request).toBe(false);
  });

  it("is off, and says Exporting, while the file is on its way, and is on again after", async () => {
    const answer = deferred<void>();
    vi.mocked(exportList).mockReturnValue(answer.promise);
    render(<ListView listKey="balances" />);
    fireEvent.click(await button());
    expect((await screen.findByRole("button", { name: "Exporting…" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Exporting…" }));
    expect(exportList).toHaveBeenCalledTimes(1);                                        // a second press does nothing
    answer.resolve();
    await waitFor(() => expect((screen.getByRole("button", { name: "Export CSV" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("says why the export failed, in the server's words, keeps the list, and can be pressed again", async () => {
    vi.mocked(exportList).mockRejectedValueOnce(new Error("Value cannot be grouped."));
    render(<ListView listKey="balances" />);
    fireEvent.click(await button());
    expect((await screen.findByRole("alert")).textContent).toBe("The list could not be exported. Value cannot be grouped.");
    expect(screen.getAllByRole("row").length).toBeGreaterThan(3);
    fireEvent.click(await screen.findByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(exportList).toHaveBeenCalledTimes(2);
  });

  it("is there for a result with no rows too, which gives the file's headers alone", async () => {
    vi.mocked(fetchList).mockResolvedValue(page({ total: 0, pages: 1, rows: [] }));
    render(<ListView listKey="balances" />);
    const export_ = await button();
    expect(export_.nextElementSibling?.textContent).toBe("0 rows");
    fireEvent.click(export_);
    await waitFor(() => expect(exportList).toHaveBeenCalledTimes(1));
  });

  it("is there when a search or a filter finds nothing, and exports that view", async () => {
    window.history.replaceState(null, "", "/balances?q=nothing");
    vi.mocked(fetchList).mockResolvedValue(page({ total: 0, pages: 1, rows: [] }));
    render(<ListView listKey="balances" />);
    expect(await screen.findByText(/No rows match/)).toBeTruthy();
    fireEvent.click(await button());
    await waitFor(() => expect(vi.mocked(exportList).mock.calls[0][1]).toMatchObject({ search: "nothing" }));
  });

  it("is not there while the list is loading or when it could not be loaded", async () => {
    vi.mocked(fetchList).mockRejectedValue(new Error("down"));
    render(<ListView listKey="balances" />);
    expect(await screen.findByText(/Could not load the list/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Export CSV/ })).toBeNull();
  });
});

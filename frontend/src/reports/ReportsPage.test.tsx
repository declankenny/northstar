// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Choices, Condition, FieldNode, FieldTree } from "../api";
import { giveBoxesASize } from "../charts/chartTesting";
import { deferred } from "../testing";
import { calculateReport, fetchReportChoices, fetchReportDefinition, fetchReports, ReportRequestError } from "./api";
import { ReportsPage } from "./ReportsPage";
import type { ReportDefinition, ReportListItem, ReportResult } from "./types";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()), fetchReports: vi.fn(), fetchReportDefinition: vi.fn(), calculateReport: vi.fn(), fetchReportChoices: vi.fn(),
}));
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()), fetchSavedFilters: vi.fn(), saveSavedFilter: vi.fn(), changeSavedFilter: vi.fn(), deleteSavedFilter: vi.fn(), saveListColumns: vi.fn(),
}));
import { changeSavedFilter, deleteSavedFilter, fetchSavedFilters, saveListColumns, saveSavedFilter } from "../api";

let restoreSizes: () => void;
beforeEach(() => {
  restoreSizes = giveBoxesASize(640, 360);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.mocked(fetchReports).mockResolvedValue(REPORTS);
  vi.mocked(fetchReportDefinition).mockImplementation(async (key) => (key === "synthetic_other" ? OTHER : DEFINITION));
  vi.mocked(calculateReport).mockResolvedValue(RESULT);
  vi.mocked(fetchReportChoices).mockResolvedValue(TYPES);
  window.history.replaceState(null, "", "/reports");
});
afterEach(() => { cleanup(); restoreSizes(); vi.clearAllMocks(); vi.restoreAllMocks(); });

const REPORTS: ReportListItem[] = [
  { key: "synthetic_as_of", title: "Synthetic as-of", description: "An as-of date with a summary, a treemap and a table." },
  { key: "synthetic_other", title: "Synthetic other", description: "A second report." },
];
const op = (name: string, label: string) => ({ name, label });
const field = (over: Partial<FieldNode>): FieldNode => ({ key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: [], choices: null, ...over });
const TREE: FieldTree = {
  fields: [field({ key: "name", label: "Name", path_label: "Name", operators: [op("contains", "contains"), op("equals", "equals")] })],
  relations: [field({ key: "type", label: "Account type", path_label: "Account type", kind: "choice", operators: [op("is_any_of", "is one of")], choices: "records" })],
};
const TYPES: Choices = { kind: "records", values: [], more: false, options: [{ id: 1, value: "Savings", detail: null }, { id: 2, value: "Checking", detail: null }] };
const OPENING: Condition = { field: "type", operator: "is_any_of", value: [1] };

const DEFINITION: ReportDefinition = {
  key: "synthetic_as_of", title: "Synthetic as-of", description: "An as-of date with a summary, a treemap and a table.", today: "2026-11-11",
  parameters: [{ key: "as_at", label: "As at", kind: "date", default: "2026-11-11", choices: [], minimum: null, maximum: null, rules: [{ rule: "not_future" }] }],
  sections: [
    { key: "headline", kind: "summary", view: "tiles", title: "Headline", sized: false, columns: 12, expanded: true },
    { key: "composition", kind: "hierarchy", view: "treemap", title: "Composition", sized: true, columns: 6, expanded: true },
    { key: "detail", kind: "rows", view: "table", title: "Detail", sized: false, columns: 6, expanded: true },
    { key: "trend", kind: "series", view: "line", title: "Trend", sized: false, columns: 12, expanded: true },
  ],
  filters: { enabled: true, fields: TREE, defaults: [] },
};
const OTHER: ReportDefinition = { ...DEFINITION, key: "synthetic_other", title: "Synthetic other", description: "A second report.", filters: { enabled: false } };
const result = (over: Partial<ReportResult> = {}, net = 123_456): ReportResult => ({
  report: "synthetic_as_of", today: "2026-11-11", parameters: { as_at: "2026-11-11" }, filters: [], currency: { code: "USD", minor_units: 2 },
  sections: {
    headline: { items: [{ key: "net", label: "Net worth", kind: "money", value: net }] },
    composition: { nodes: [{ id: "a", label: "Savings", value: 300, size: 300 }, { id: "b", label: "Checking", value: 100, size: 100 }] },
    detail: { columns: [{ key: "name", label: "Account", kind: "text" }], rows: [{ id: "r1", cells: { name: "Alpha" } }] },
    trend: { series: [] },
  },
  notes: [], ...over,
});
const RESULT = result();
const show = (path = "/reports", isAdmin = true) => { window.history.replaceState(null, "", path); return render(<ReportsPage isAdmin={isAdmin} />); };
const date = () => screen.getByLabelText("As at") as HTMLInputElement;
const requests = () => vi.mocked(calculateReport).mock.calls.map((c) => c[1]);
const settle = () => act(async () => { await Promise.resolve(); });

describe("the Reports page", () => {
  it("says so when there are no reports yet", async () => {
    vi.mocked(fetchReports).mockResolvedValue([]);
    show();
    expect(await screen.findByText("There are no reports yet.")).toBeTruthy();
    expect(fetchReportDefinition).not.toHaveBeenCalled();
  });

  it("opens the first report when the address names none, without a history entry, and shows its name and description", async () => {
    const before = window.history.length;
    show("/reports");
    expect(await screen.findByDisplayValue("Synthetic as-of")).toBeTruthy();
    expect(window.location.pathname).toBe("/reports/synthetic_as_of");
    expect(window.history.length).toBe(before);
    expect(screen.getByText("An as-of date with a summary, a treemap and a table.")).toBeTruthy();
    expect(fetchReportDefinition).toHaveBeenCalledWith("synthetic_as_of", expect.anything());
  });

  it("says a report that does not exist (or may not be seen) is not found, and offers the first", async () => {
    show("/reports/nothing");
    expect(await screen.findByRole("heading", { name: "Report not found" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Open Synthetic as-of/ }));
    expect(window.location.pathname).toBe("/reports/synthetic_as_of");
  });

  it("says when the reports or a definition could not be loaded, and tries again", async () => {
    vi.mocked(fetchReports).mockRejectedValueOnce(new Error("The server answered 500"));
    show("/reports/synthetic_as_of");
    expect(await screen.findByText(/Could not load the reports/)).toBeTruthy();
    cleanup();
    vi.mocked(fetchReportDefinition).mockRejectedValueOnce(new Error("The server answered 500"));
    show("/reports/synthetic_as_of");
    expect(await screen.findByText(/Could not load this report/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("As at")).toBeTruthy();
  });

  it("changes report from the name: another address, another report's definition, and its own defaults", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByLabelText("As at");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });
    const input = screen.getByRole("combobox", { name: "Report" });
    fireEvent.click(input);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Synthetic as-ofAn as-of date with a summary, a treemap and a table.", "Synthetic otherA second report."]);
    fireEvent.mouseDown(screen.getByRole("option", { name: /Synthetic other/ }));
    await waitFor(() => expect(window.location.pathname).toBe("/reports/synthetic_other"));
    expect(await screen.findByDisplayValue("Synthetic other")).toBeTruthy();
    expect(date().value).toBe("2026-11-11");                                       // not the date chosen in the other report
    expect(screen.queryByRole("button", { name: /^Filters/ })).toBeNull();          // this one cannot be filtered
  });
});

describe("a report's page", () => {
  it("asks for the report once at its defaults, naming every parameter and sending no filters", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    expect(requests()).toEqual([{ parameters: { as_at: "2026-11-11" }, filters: [] }]);
  });

  it("puts the headline figures in the header and the other sections in the grid, in the order declared, each as wide as it asked", async () => {
    const { container } = show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    expect(container.querySelector(".rp-top .rp-tiles")!.textContent).toContain("Net worth");
    expect(container.querySelector(".rp-grid .tile")).toBeNull();
    const cards = [...container.querySelectorAll(".rp-grid > section")];
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["Composition", "Detail", "Trend"]);
    expect(cards.map((c) => c.className.match(/rp-span-(\d+)/)![1])).toEqual(["6", "6", "12"]);
    expect(within(cards[1] as HTMLElement).getByText("Alpha")).toBeTruthy();
    expect(within(cards[2] as HTMLElement).getByText("This kind of chart is not available yet.")).toBeTruthy();
  });

  it("asks again, with every parameter named, when a valid choice changes, and shows the new answer", async () => {
    vi.mocked(calculateReport).mockResolvedValueOnce(RESULT).mockResolvedValueOnce(result({}, 999_900));
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });
    expect(await screen.findByText("$9,999.00")).toBeTruthy();
    expect(requests()).toEqual([{ parameters: { as_at: "2026-11-11" }, filters: [] }, { parameters: { as_at: "2026-06-30" }, filters: [] }]);
  });

  it("asks nothing and shows nothing stale under a choice that cannot be asked for, and says what is wrong", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-12-01" } });
    expect(await screen.findByText(/Choose today or an earlier date/)).toBeTruthy();
    expect(screen.getByText("Fix the highlighted choice to see the report.")).toBeTruthy();
    expect(screen.queryByText("$1,234.56")).toBeNull();
    expect(screen.queryByText("Savings")).toBeNull();
    expect(calculateReport).toHaveBeenCalledTimes(1);
    expect(date().getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(date(), { target: { value: "2026-11-10" } });                    // and fixing it asks again
    await waitFor(() => expect(calculateReport).toHaveBeenCalledTimes(2));
    expect(requests()[1]).toEqual({ parameters: { as_at: "2026-11-10" }, filters: [] });
  });

  it("never lets a slow answer replace a newer one", async () => {
    const slow = deferred<ReportResult>(), fast = deferred<ReportResult>();
    vi.mocked(calculateReport).mockResolvedValueOnce(RESULT).mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });                    // the first question, which is slow
    fireEvent.change(date(), { target: { value: "2026-07-31" } });                    // the second, which is newer
    fast.resolve(result({}, 222_200));
    expect(await screen.findByText("$2,222.00")).toBeTruthy();
    slow.resolve(result({}, 111_100));                                                // the older answer lands last
    await settle();
    expect(screen.getByText("$2,222.00")).toBeTruthy();
    expect(screen.queryByText("$1,111.00")).toBeNull();
  });

  it("dims what is on screen while the next answer is on its way, and marks it busy", async () => {
    const next = deferred<ReportResult>();
    vi.mocked(calculateReport).mockResolvedValueOnce(RESULT).mockReturnValueOnce(next.promise);
    const { container } = show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });
    await waitFor(() => expect(container.querySelector(".rp-body")!.getAttribute("aria-busy")).toBe("true"));
    expect(container.querySelector(".rp-body")!.className).toContain("rp-busy");
    expect(screen.getByText("$1,234.56")).toBeTruthy();                                // the old figures stay, dimmed
    next.resolve(result({}, 5_000));
    await screen.findByText("$50.00");
    expect(container.querySelector(".rp-body")!.getAttribute("aria-busy")).toBe("false");
  });

  it("shows notes: a general one above the grid and a section's own under it", async () => {
    vi.mocked(calculateReport).mockResolvedValue(result({ notes: [{ code: "all", text: "Figures as entered." }, { code: "one", text: "One account is overdrawn.", section: "detail" }] }));
    const { container } = show("/reports/synthetic_as_of");
    expect(await screen.findByText("Figures as entered.")).toBeTruthy();
    expect(container.querySelector(".rp-grid")!.previousElementSibling!.textContent).toBe("Figures as entered.");
    expect(within(container.querySelector('[aria-label="Detail"]') as HTMLElement).getByText("One account is overdrawn.")).toBeTruthy();
  });

  it("shows the headline's own notes with the headline, in the header and not in the grid", async () => {
    vi.mocked(calculateReport).mockResolvedValue(result({ notes: [{ code: "basis", text: "Figures use the latest balance.", section: "headline" }] }));
    const { container } = show("/reports/synthetic_as_of");
    expect(await screen.findByText("Figures use the latest balance.")).toBeTruthy();
    expect(container.querySelector(".rp-summary")!.textContent).toContain("Figures use the latest balance.");
    expect(container.querySelector(".rp-grid")!.textContent).not.toContain("Figures use the latest balance.");
  });

  it("draws a hierarchy as a table without failing the page", async () => {
    vi.mocked(fetchReportDefinition).mockResolvedValue({ ...DEFINITION, sections: [{ key: "tree", kind: "hierarchy", view: "table", title: "Tree", sized: false, columns: 12, expanded: true }] });
    vi.mocked(calculateReport).mockResolvedValue(result({ sections: { tree: { nodes: [{ id: "a", label: "Savings", value: 300, children: [{ id: "a1", label: "Emergency fund", value: 300 }] }] } } }));
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "Tree" })).toBeTruthy();
    expect(screen.getByText("Emergency fund")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Report" })).toBeTruthy();            // the page is still there
  });

  it("says what the report says when it reports `no_data`, though its headline has figures, and offers to clear the filters", async () => {
    vi.mocked(calculateReport).mockResolvedValue(result({ notes: [{ code: "no_data", text: "There are no accounts to show." }] }, 0));
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "Nothing to show" })).toBeTruthy();
    expect(screen.getByText("There are no accounts to show.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Composition" })).toBeNull();
  });

  it("says there is nothing to show when every section is empty, and offers to clear the filters when there are some", async () => {
    const empty = result({}, 0);
    empty.sections = { headline: { items: [] }, composition: { nodes: [] }, detail: { columns: [], rows: [] }, trend: { series: [] } };
    vi.mocked(calculateReport).mockResolvedValue(empty);
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "Nothing to show" })).toBeTruthy();
    expect(screen.getByText("There is nothing to show for these choices.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });
});

describe("when a report cannot be worked out", () => {
  const fail = (error: ReportRequestError) => vi.mocked(calculateReport).mockRejectedValue(error);

  it("says a missing exchange rate stops the whole report, shows no figures, and sends an administrator to the currencies", async () => {
    fail(new ReportRequestError("There is no EUR rate on or before 15 Feb 2026, so the figures cannot be worked out.", "unavailable_data", 422, [], "missing_rates", ["EUR"]));
    show("/reports/synthetic_as_of", true);
    expect(await screen.findByRole("heading", { name: "The report cannot be worked out yet" })).toBeTruthy();
    expect(screen.getByText(/There is no EUR rate on or before 15 Feb 2026/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add rates on Currencies" }).getAttribute("href")).toBe("/currencies");
    expect(screen.queryByText("Savings")).toBeNull();
  });

  it("tells anyone else to ask an administrator, and sends an administrator to the system properties when the currency is not chosen", async () => {
    fail(new ReportRequestError("An administrator has not chosen the system currency yet.", "unavailable_data", 422, [], "no_system_currency"));
    show("/reports/synthetic_as_of", false);
    expect(await screen.findByText("Ask an administrator.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    cleanup();
    show("/reports/synthetic_as_of", true);
    expect((await screen.findByRole("link", { name: "Choose it on System properties" })).getAttribute("href")).toBe("/system-properties");
  });

  it("says what the server refused, when it refuses something the page let through", async () => {
    fail(new ReportRequestError("“Created” is a date, and this report cannot be filtered by dates.", "invalid_input", 422, ["filters", 0, "field"]));
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "That cannot be asked for" })).toBeTruthy();
    expect(screen.getByText(/this report cannot be filtered by dates/)).toBeTruthy();
  });

  it("says a broken report is on our side, shows no figures, and asks again on request", async () => {
    vi.mocked(calculateReport).mockRejectedValueOnce(new ReportRequestError("The report could not be worked out.", "calculation_error", 500)).mockResolvedValue(RESULT);
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "The report could not be worked out" })).toBeTruthy();
    expect(screen.getByText(/Something went wrong on our side/)).toBeTruthy();
    expect(screen.queryByText("$1,234.56")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("$1,234.56")).toBeTruthy();
  });

  it("leaves no figures on screen, the headline's included, when a later request fails to reach the server", async () => {
    vi.mocked(calculateReport).mockResolvedValueOnce(RESULT).mockRejectedValueOnce(new Error("Failed to fetch"));
    const { container } = show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });
    expect(await screen.findByRole("heading", { name: "The report could not be worked out" })).toBeTruthy();
    expect(screen.queryByText("$1,234.56")).toBeNull();
    expect(container.querySelector(".rp-tiles")).toBeNull();
    expect(container.querySelector(".rp-grid")).toBeNull();
  });

  it("treats an answer that is not a report's (a network failure) as a failure too, never as figures", async () => {
    vi.mocked(calculateReport).mockRejectedValue(new Error("Failed to fetch"));
    show("/reports/synthetic_as_of");
    expect(await screen.findByRole("heading", { name: "The report could not be worked out" })).toBeTruthy();
    expect(screen.queryByText("Net worth")).toBeNull();
  });
});

describe("filters on a report", () => {
  const withDefaults = () => vi.mocked(fetchReportDefinition).mockResolvedValue({ ...DEFINITION, filters: { enabled: true, fields: TREE, defaults: [OPENING] } });

  it("open with the report's own, shown as chips and sent with the first request", async () => {
    withDefaults();
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    expect(requests()).toEqual([{ parameters: { as_at: "2026-11-11" }, filters: [OPENING] }]);
    expect(screen.getByRole("button", { name: /^Filters \(1\)/ })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("list", { name: "Filters applied" }).textContent).toContain("Account type is one of Savings"));
  });

  it("stay cleared once cleared, which sends an empty list and not the defaults, and a removed one is not brought back", async () => {
    withDefaults();
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(calculateReport).toHaveBeenCalledTimes(2));
    expect(requests()[1]).toEqual({ parameters: { as_at: "2026-11-11" }, filters: [] });
    fireEvent.change(date(), { target: { value: "2026-06-30" } });                     // a parameter change keeps them cleared
    await waitFor(() => expect(calculateReport).toHaveBeenCalledTimes(3));
    expect(requests()[2]).toEqual({ parameters: { as_at: "2026-06-30" }, filters: [] });
  });

  it("are made in the report's own drawer: no saved filters, no Columns, nothing asked of the lists' endpoints; Apply asks again and gives focus back", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    const button = screen.getByRole("button", { name: /^Filters/ });
    button.focus();
    fireEvent.click(button);
    const drawer = within(await screen.findByRole("dialog", { name: "Synthetic as-of filters" }));
    expect(drawer.queryByText("Saved filter")).toBeNull();
    expect(drawer.queryByRole("button", { name: /^Columns/ })).toBeNull();
    fireEvent.click(drawer.getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(screen.getByLabelText("Fields to filter by")).getByRole("button", { name: "Name" }));
    fireEvent.change(drawer.getByLabelText("Name"), { target: { value: "joint" } });
    fireEvent.click(drawer.getByRole("button", { name: "Apply changes" }));
    await waitFor(() => expect(calculateReport).toHaveBeenCalledTimes(2));
    expect(requests()[1]).toEqual({ parameters: { as_at: "2026-11-11" }, filters: [{ field: "name", operator: "contains", value: "joint" }] });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Filters \(1\)/ }));
    for (const lists of [fetchSavedFilters, saveSavedFilter, changeSavedFilter, deleteSavedFilter, saveListColumns]) expect(lists).not.toHaveBeenCalled();
  });

  it("fetch the names of a record's choices from the report, and nothing from a list", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
    const drawer = within(await screen.findByRole("dialog"));
    fireEvent.click(drawer.getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(screen.getByLabelText("Fields to filter by")).getByRole("button", { name: "Account type" }));
    await waitFor(() => expect(fetchReportChoices).toHaveBeenCalledWith("synthetic_as_of", "type"));
    expect(await drawer.findByRole("checkbox", { name: "Savings" })).toBeTruthy();
  });

  it("cancel throws the draft away", async () => {
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
    const drawer = within(await screen.findByRole("dialog"));
    fireEvent.click(drawer.getByRole("button", { name: "+ Add filter" }));
    fireEvent.click(within(screen.getByLabelText("Fields to filter by")).getByRole("button", { name: "Name" }));
    fireEvent.click(drawer.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calculateReport).toHaveBeenCalledTimes(1);
  });
});

describe("opening a report", () => {
  it("starts at its defaults every time: nothing chosen is kept in the address, the browser or anywhere else", async () => {
    const stored = vi.spyOn(Storage.prototype, "setItem");
    const first = show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    fireEvent.change(date(), { target: { value: "2026-06-30" } });
    await waitFor(() => expect(calculateReport).toHaveBeenCalledTimes(2));
    expect(window.location.search).toBe("");
    first.unmount();
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    expect(date().value).toBe("2026-11-11");
    expect(requests()[2]).toEqual({ parameters: { as_at: "2026-11-11" }, filters: [] });
    expect(stored).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });

  it("starts at the server's today, which the page reads from the definition and never from the browser's clock", async () => {
    vi.mocked(fetchReportDefinition).mockResolvedValue({ ...DEFINITION, today: "2031-03-04", parameters: [{ ...DEFINITION.parameters[0], default: "2031-03-04" }] });
    show("/reports/synthetic_as_of");
    await screen.findByText("$1,234.56");
    expect(date().value).toBe("2031-03-04");
    expect(requests()[0].parameters).toEqual({ as_at: "2031-03-04" });
    fireEvent.change(date(), { target: { value: "2031-03-05" } });
    expect(await screen.findByText(/Choose today or an earlier date/)).toBeTruthy();    // later than the server's today, though long before the browser's
  });
});

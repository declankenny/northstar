// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountPage, ImportColumn, ImportRead, ImportReview, ImportRow } from "./api";
import { ImportBalances } from "./ImportBalances";
import { navigate } from "./router";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchAccount: vi.fn(), fetchImportRead: vi.fn(), fetchImportReview: vi.fn(), commitImport: vi.fn(),
}));

import { commitImport, fetchAccount, fetchImportRead, fetchImportReview, RequestError } from "./api";

const ALL_FORMATS = ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY", "DD.MM.YYYY"];
const CSV = "Date,Balance,Note\n2026-01-31,1000.00,Opening\n2026-02-28,1100.50,\n2026-03-31,1200.00,Bonus\n";

const account = (over: Partial<AccountPage> = {}): AccountPage => ({
  id: 7, name: "Demo Savings", class_name: "Asset", type_id: 1, type_name: "Savings", is_open: true, notes: null, stale_after_days: 30,
  balance_count: 0, earliest_date: null, last_date: null, last_cents: null, days_since: null, stale: false, balances: [],
  types: [], other_class: { id: 2, name: "Liability", types: [] }, today: "2026-10-30", ...over,
});

const column = (index: number, header: string, samples: string[], date_formats: string[] = []): ImportColumn => ({ index, header, samples, date_formats, number_formats: [], number_previews: {} });

const readOf = (over: Partial<ImportRead> = {}): ImportRead => ({
  currency: {code: "USD", name: "US Dollar", minor_units: 2}, number_formats: ["1,234.56"], canonical: false,
  delimiter: ",", row_count: 3, today: "2026-10-30", date_formats: ALL_FORMATS,
  columns: [column(0, "Date", ["2026-01-31", "2026-02-28", "2026-03-31"], ["YYYY-MM-DD"]), column(1, "Balance", ["1000.00", "1100.50", "1200.00"]),
    column(2, "Note", ["Opening", "Bonus"])],
  suggested: { date: 0, balance: 1, note: 2 }, ...over,
});

const row = (record: number, date: string, outcome: ImportRow["outcome"], cents: number, old: number | null = null): ImportRow => ({
  record, date, outcome, amount_cents: cents, old_cents: old, note: null, old_note: null, result_note: null,
});

const reviewOf = (over: Partial<ImportReview> = {}): ImportReview => ({
  can_commit: true, errors: [], notes: [], date_format: "YYYY-MM-DD",
  counts: { add: 2, replace: 0, unchanged: 0, skip: 1 },
  rows: [row(4, "2026-03-31", "add", 120000), row(3, "2026-02-28", "skip", 110050, 99999), row(2, "2026-01-31", "add", 100000)],
  hidden: {}, reviewed: { fingerprint: "abc", expectations: [{ date: "2026-01-31", balance_id: null, version: null }] }, ...over,
});

const pick = (text = CSV, name = "statement.csv") =>
  fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [new File([text], name, { type: "text/csv" })] } });

async function toMap(read = readOf()) {
  vi.mocked(fetchImportRead).mockResolvedValue(read);
  render(<ImportBalances id={7} />);
  await screen.findByText("Choose a CSV file");
  pick();
  await screen.findByText(/Tell Northstar what each column holds/);
}

describe("the Northstar CSV in the number style box", () => {
  const exported = (suggested: ImportRead["suggested"], over: Partial<ImportRead> = {}) => readOf({
    canonical: true, suggested,
    columns: [column(0, "Account ID", ["1"]), column(1, "Account Name", ["Demo"]), column(2, "Balance Date", ["2026-01-31"], ["YYYY-MM-DD"]),
      column(3, "Balance Amount", ["1234.56"])].map((c) => (c.index === 3 ? { ...c, number_formats: ["1234.56"] } : c)), ...over });

  it("says the amounts are plain decimals, wherever the server says the balance and date are", async () => {
    await toMap(exported({ date: 2, balance: 3, note: null }));
    expect(screen.getByText("Plain decimal (Northstar CSV)")).toBeTruthy();
    expect(screen.queryByLabelText("Number style")).toBeNull();
  });

  it("follows the columns the server suggested and not fixed positions", async () => {
    await toMap(exported({ date: 0, balance: 3, note: null }));          // the server says the date is in column 0 and the balance in 3
    expect(screen.getByText("Plain decimal (Northstar CSV)")).toBeTruthy();
    expect(screen.queryByLabelText("Number style")).toBeNull();
  });

  it("shows the choice when the file is not the Northstar CSV, even with the same columns", async () => {
    await toMap(exported({ date: 2, balance: 3, note: null }, { canonical: false }));
    expect(screen.queryByText("Plain decimal (Northstar CSV)")).toBeNull();
    expect(screen.getByLabelText("Number style")).toBeTruthy();
  });
});

async function toReview(review = reviewOf(), read = readOf()) {
  vi.mocked(fetchImportReview).mockResolvedValue(review);
  await toMap(read);
  fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
  await screen.findByText(/Nothing has been saved yet|The file has/);
}

const useOf = (header: string) => screen.getByLabelText(`Use of column ${header}`) as HTMLSelectElement;
const lastReview = () => vi.mocked(fetchImportReview).mock.calls.at(-1)![1];

const dinars = (): ImportRead => readOf({
  currency: { code: "KWD", name: "Kuwaiti Dinar", minor_units: 3 },
  number_formats: ["1,234.56", "1.234,56"],
  columns: [column(0, "Date", ["2026-01-31"], ["YYYY-MM-DD"]), {
    ...column(1, "Balance", ["1.234"]), number_formats: ["1,234.56", "1.234,56"],
    number_previews: { "1,234.56": 1234, "1.234,56": 1234000 },
  }], suggested: { date: 0, balance: 1, note: null },
});

it("requires an ambiguous number style inline and carries the chosen interpretation into review and commit", async () => {
  vi.mocked(fetchImportReview).mockResolvedValue(reviewOf({rows: [row(2, "2026-01-31", "add", 1234000)]}));
  vi.mocked(commitImport).mockResolvedValue({ added: 1, updated: 0, unchanged: 0, skipped: 0 });
  await toMap(dinars());
  const next = screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement;
  expect(next.disabled).toBe(true);
  const picker = screen.getByLabelText("Number style");
  expect(picker.closest(".imp-use")).toBe(useOf("Balance").closest(".imp-use"));
  expect(within(useOf("Balance")).queryByRole("option", {name: "Currency"})).toBeNull();
  fireEvent.change(picker, { target: { value: "1.234,56" } });
  expect(screen.getByText(/1.234 reads as KWD 1,234.000/)).toBeTruthy();
  expect(next.disabled).toBe(false);
  fireEvent.click(next);
  await screen.findByText(/all balances are treated as KWD/);
  expect(lastReview().numberFormat).toBe("1.234,56");
  expect(screen.getByText("KWD 1,234.000")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
  await screen.findByText(/Imported from/);
  expect(vi.mocked(commitImport).mock.calls[0][1].numberFormat).toBe("1.234,56");
});

it("clears the number style when the Balance mapping changes", async () => {
  await toMap(dinars());
  fireEvent.change(screen.getByLabelText("Number style"), {target: {value: "1,234.56"}});
  fireEvent.change(useOf("Balance"), {target: {value: "ignore"}});
  fireEvent.change(useOf("Balance"), {target: {value: "balance"}});
  expect((screen.getByLabelText("Number style") as HTMLSelectElement).value).toBe("");
  expect((screen.getByRole("button", {name: "Continue to review"}) as HTMLButtonElement).disabled).toBe(true);
});

beforeEach(() => {
  vi.mocked(fetchAccount).mockResolvedValue(account());
  window.history.replaceState(null, "", "/accounts/7/import");
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.restoreAllMocks();
});

describe("Import: the account and the first screen", () => {
  it("names the account and says what a file may be", async () => {
    render(<ImportBalances id={7} />);
    expect(await screen.findByRole("heading", { name: "Demo Savings" })).toBeTruthy();
    expect(screen.getByText("Choose a CSV file")).toBeTruthy();
    expect(screen.getByText(/up to 2 MB and 20,000 rows/)).toBeTruthy();
    expect(screen.getByText(/not kept/)).toBeTruthy();
    expect(screen.getByRole("group", { name: "Steps" }).textContent).toContain("1 Choose file");
  });

  it("does not offer to import into a closed account", async () => {
    vi.mocked(fetchAccount).mockResolvedValue(account({ is_open: false }));
    render(<ImportBalances id={7} />);
    expect(await screen.findByText(/This account is closed. Reopen it to import balances/)).toBeTruthy();
    expect(screen.queryByText("Choose a CSV file")).toBeNull();
  });

  it("says when the account cannot be loaded", async () => {
    vi.mocked(fetchAccount).mockRejectedValue(new Error("That account no longer exists."));
    render(<ImportBalances id={7} />);
    expect(await screen.findByText(/Could not load this account. That account no longer exists./)).toBeTruthy();
  });

  it("sends the file as base64 with its name, and moves on to the columns", async () => {
    await toMap();
    const [accountId, sent] = vi.mocked(fetchImportRead).mock.calls[0];
    expect(accountId).toBe(7);
    expect(sent.name).toBe("statement.csv");
    expect(atob(sent.content)).toBe(CSV);
  });

  it("refuses a file over 2 MB in the browser, without sending it", async () => {
    render(<ImportBalances id={7} />);
    await screen.findByText("Choose a CSV file");
    pick("x".repeat(2 * 1024 * 1024 + 1), "big.csv");
    expect(await screen.findByText(/larger than 2 MB/)).toBeTruthy();
    expect(fetchImportRead).not.toHaveBeenCalled();
  });

  it("shows why a file was refused and stays on the first screen", async () => {
    vi.mocked(fetchImportRead).mockRejectedValue(new RequestError("The file is not UTF-8 text.", {}, 422));
    render(<ImportBalances id={7} />);
    await screen.findByText("Choose a CSV file");
    pick();
    expect(await screen.findByText("The file is not UTF-8 text.")).toBeTruthy();
    expect(screen.queryByText(/Tell Northstar what each column holds/)).toBeNull();
  });
});

describe("Import: mapping the columns", () => {
  it("prefills the clear matches and the date format the data decides, so Continue is ready", async () => {
    await toMap();
    expect([useOf("Date").value, useOf("Balance").value, useOf("Note").value]).toEqual(["date", "balance", "note"]);
    expect((screen.getByLabelText("Date format") as HTMLSelectElement).value).toBe("YYYY-MM-DD");
    expect(screen.getByText("All set.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows the file's name, size and delimiter, and each column's first values", async () => {
    await toMap(readOf({ delimiter: ";" }));
    expect(screen.getByText("statement.csv")).toBeTruthy();
    expect(screen.getByText(/semicolon separated/)).toBeTruthy();
    expect(screen.getByText("1100.50")).toBeTruthy();
  });

  it("moves a use to the column just chosen, so no use is on two columns", async () => {
    await toMap();
    fireEvent.change(useOf("Note"), { target: { value: "balance" } });
    expect([useOf("Balance").value, useOf("Note").value]).toEqual(["ignore", "balance"]);
    expect(screen.getByText("All set.")).toBeTruthy();                       // the balance is on the Note column now, so it is still mapped
  });

  it("will not continue without a Date or a Balance, and says which", async () => {
    await toMap();
    fireEvent.change(useOf("Balance"), { target: { value: "ignore" } });
    expect(screen.getByText("Choose which column holds the balance.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(useOf("Balance"), { target: { value: "balance" } });
    fireEvent.change(useOf("Date"), { target: { value: "ignore" } });
    expect(screen.getByText("Choose which column holds the date.")).toBeTruthy();
  });

  it("makes the person choose a date format that the data cannot decide, and then continues", async () => {
    const ambiguous = readOf({
      columns: [column(0, "Date", ["01/02/2026", "03/04/2026"], ["MM/DD/YYYY", "DD/MM/YYYY"]), column(1, "Balance", ["10.00", "11.00"])],
      suggested: { date: 0, balance: 1, note: null },
    });
    await toMap(ambiguous);
    expect(screen.getByText(/can be read more than one way/)).toBeTruthy();
    expect(screen.getByText("Choose the date format to continue.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement).disabled).toBe(true);
    const formats = within(screen.getByLabelText("Date format")).getAllByRole("option").map((o) => o.textContent);
    expect(formats).toEqual(["Choose…", "MM/DD/YYYY", "DD/MM/YYYY"]);          // only the formats that fit

    fireEvent.change(screen.getByLabelText("Date format"), { target: { value: "DD/MM/YYYY" } });
    expect((screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement).disabled).toBe(false);
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf());
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    await screen.findByText(/Nothing has been saved yet/);
    expect(lastReview().dateFormat).toBe("DD/MM/YYYY");
  });

  it("lets the review list the values when no date format fits", async () => {
    const broken = readOf({ columns: [column(0, "Date", ["2026-01-31", "oops"], []), column(1, "Balance", ["1", "2"])], suggested: { date: 0, balance: 1, note: null } });
    await toMap(broken);
    expect(screen.getByText(/Some values are not dates in a format Northstar reads/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue to review" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("goes back to the first screen with Back and keeps the file", async () => {
    await toMap();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Choose a CSV file")).toBeTruthy();
    expect(fetchImportRead).toHaveBeenCalledTimes(1);
  });
});

describe("Import: the review", () => {
  it("says what will happen, in counts and in a list with old and new amounts", async () => {
    await toReview();
    expect(screen.getByText(/all balances are treated as USD/)).toBeTruthy();
    const counts = within(screen.getByLabelText("What will happen"));
    expect(counts.getByText("will be added").previousSibling?.textContent).toBe("2");
    expect(counts.getByText("left alone (skipped)").previousSibling?.textContent).toBe("1");
    const list = within(screen.getByLabelText("Changes"));
    const skipped = list.getByText("Feb 28, 2026").closest("tr")!;
    expect(skipped.textContent).toContain("Skip");
    expect(skipped.textContent).toContain("$999.99");
    expect(skipped.textContent).toContain("$1,100.50");
    expect(list.getAllByRole("row").slice(1).map((r) => (r as HTMLTableRowElement).cells[0].textContent)).toEqual(["Mar 31, 2026", "Feb 28, 2026", "Jan 31, 2026"]);
    expect(screen.getByText(/2 balances will be added. It can be undone from the Imports page./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import 2 balances" })).toBeTruthy();
  });

  it("asks the server again when the policy changes", async () => {
    await toReview();
    expect(lastReview().policy).toBe("skip");
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf({ counts: { add: 2, replace: 1, unchanged: 0, skip: 0 } }));
    fireEvent.click(screen.getByLabelText(/Replace them with the file's amount/));
    expect(await screen.findByRole("button", { name: "Import 3 balances" })).toBeTruthy();
    expect(lastReview().policy).toBe("replace");
  });

  it("sends the mapping by position, with Ignore as nothing", async () => {
    await toMap();
    fireEvent.change(useOf("Note"), { target: { value: "ignore" } });
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf());
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    await screen.findByText(/Nothing has been saved yet/);
    expect(lastReview().mapping).toEqual({ date: 0, balance: 1, note: null });
  });

  it("says how many more there are than are listed", async () => {
    await toReview(reviewOf({ hidden: { add: 250, skip: 3 } }));
    expect(screen.getByText(/Showing the newest 200 changes of each kind. Also: 250 more to add, 3 more to skip./)).toBeTruthy();
  });

  it("lists every problem and offers no Import, only a corrected file", async () => {
    await toReview(reviewOf({
      can_commit: false, counts: null, rows: [], reviewed: null,
      errors: [{ record: 4, column: 1, message: '"12x" is not an amount.' }, { record: null, column: null, message: "The file has EUR." }],
    }));
    expect(screen.getByText(/The file has 2 problems/)).toBeTruthy();
    expect(screen.getByText('Record 4: "12x" is not an amount.')).toBeTruthy();
    expect(screen.getByText("The file has EUR.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Import \d/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Choose corrected file…" })).toBeTruthy();
  });

  it("does not offer to import when nothing would be written", async () => {
    await toReview(reviewOf({ counts: { add: 0, replace: 0, unchanged: 3, skip: 0 }, rows: [] }));
    expect(screen.getByText(/Nothing will be written/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Import 0 balances" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("No dates would change.")).toBeTruthy();
  });

  it("keeps the choices when going back and forward", async () => {
    await toMap();
    fireEvent.change(useOf("Note"), { target: { value: "ignore" } });
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf());
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    await screen.findByText(/Nothing has been saved yet/);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(useOf("Note").value).toBe("ignore");
  });
});

describe("Import: importing", () => {
  const done = { added: 2, updated: 0, unchanged: 0, skipped: 1 };

  it("sends exactly what was reviewed, then reports the counts and links back to the account", async () => {
    await toReview();
    vi.mocked(commitImport).mockResolvedValue(done);
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    expect(await screen.findByText("Imported from statement.csv.")).toBeTruthy();
    const [accountId, settings, reviewed] = vi.mocked(commitImport).mock.calls[0];
    expect(accountId).toBe(7);
    expect(settings.policy).toBe("skip");
    expect(reviewed.fingerprint).toBe("abc");
    const counts = within(screen.getByLabelText("What was imported"));
    expect(counts.getByText("added").previousSibling?.textContent).toBe("2");
    expect(counts.getByText("skipped").previousSibling?.textContent).toBe("1");
    expect(screen.getByRole("button", { name: "Exit" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Back to/ })).toBeNull();           // Exit replaced the link back to the account
  });

  it("cannot be pressed twice while it is importing", async () => {
    await toReview();
    let finish!: (value: typeof done) => void;
    vi.mocked(commitImport).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    const busy = await screen.findByRole("button", { name: "Importing…" }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    fireEvent.click(busy);
    expect(commitImport).toHaveBeenCalledTimes(1);
    await act(async () => finish(done));
    expect(await screen.findByText("Imported from statement.csv.")).toBeTruthy();
  });

  it("goes back to an updated review when the balances changed, and marks the dates that changed", async () => {
    await toReview();
    vi.mocked(commitImport).mockRejectedValueOnce(new RequestError(
      "Balances changed since you reviewed this import (2026-02-28). Nothing was imported. Review it again before importing.", {}, 409, ["2026-02-28"]));
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf({ counts: { add: 2, replace: 1, unchanged: 0, skip: 0 }, rows: [
      row(4, "2026-03-31", "add", 120000), row(3, "2026-02-28", "replace", 110050, 5), row(2, "2026-01-31", "add", 100000)] }));
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    expect(await screen.findByText(/Balances changed since you reviewed this import \(2026-02-28\)/)).toBeTruthy();
    expect(screen.getByText(/The review below is up to date/)).toBeTruthy();
    expect(vi.mocked(fetchImportReview)).toHaveBeenCalledTimes(2);
    const changed = within(screen.getByLabelText("Changes")).getByText("Feb 28, 2026").closest("tr")!;
    expect(changed.textContent).toContain("changed");
    expect(within(screen.getByLabelText("Changes")).getByText("Jan 31, 2026").closest("tr")!.textContent).not.toContain("changed");

    vi.mocked(commitImport).mockResolvedValue({ added: 2, updated: 1, unchanged: 0, skipped: 0 });
    fireEvent.click(await screen.findByRole("button", { name: "Import 3 balances" }));
    expect(await screen.findByText("Imported from statement.csv.")).toBeTruthy();
  });

  it("says nothing was saved when the import fails for another reason, and keeps the review", async () => {
    await toReview();
    vi.mocked(commitImport).mockRejectedValue(new RequestError("The server answered 500", {}, 500));
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    expect(await screen.findByText("Nothing was saved. The server answered 500")).toBeTruthy();
    expect(screen.getByLabelText("Changes")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Import 2 balances" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("starts again for another file", async () => {
    await toReview();
    vi.mocked(commitImport).mockResolvedValue(done);
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    fireEvent.click(await screen.findByRole("button", { name: "Import another file" }));
    expect(screen.getByText("Choose a CSV file")).toBeTruthy();
  });
});

describe("Import: choosing another file", () => {
  it("starts over from the first step with the new file's own choices", async () => {
    await toMap();
    fireEvent.change(useOf("Note"), { target: { value: "ignore" } });
    vi.mocked(fetchImportRead).mockResolvedValue(readOf({ row_count: 9 }));
    pick("Date,Balance,Note\n2026-04-30,5.00,x\n", "other.csv");
    await screen.findByText("other.csv");
    expect(vi.mocked(fetchImportRead).mock.calls.at(-1)![1].name).toBe("other.csv");
    expect(useOf("Note").value).toBe("note");                               // the choice made for the first file is gone
  });

  it("can choose the same file again", async () => {
    await toMap();
    pick();
    await vi.waitFor(() => expect(fetchImportRead).toHaveBeenCalledTimes(2));
  });
});

describe("Import: Cancel and Exit", () => {
  // The page was opened from the account page, so there is a page of the app to go back to.
  const openedFromTheAccount = () => {
    window.history.replaceState({ idx: 0 }, "", "/accounts/7");
    window.history.pushState({ idx: 1 }, "", "/accounts/7/import");
  };
  const footer = () => Array.from(document.querySelectorAll(".ub-foot button")).map((b) => b.textContent);
  const before = (first: HTMLElement, second: HTMLElement) => !!(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("puts a red Cancel to the left of Choose file… on the first screen", async () => {
    render(<ImportBalances id={7} />);
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    expect(cancel.className).toContain("danger");
    expect(before(cancel, screen.getByRole("button", { name: "Choose file…" }))).toBe(true);
  });

  it("puts Cancel, Back and the main button together, in that order, on the mapping and the review", async () => {
    await toMap();
    expect(footer()).toEqual(["Cancel", "Back", "Continue to review"]);
    vi.mocked(fetchImportReview).mockResolvedValue(reviewOf());
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    await screen.findByText(/Nothing has been saved yet/);
    expect(footer()).toEqual(["Cancel", "Back", "Import 2 balances"]);
  });

  it("keeps Cancel and Back beside the corrected-file button when the file has problems", async () => {
    await toReview(reviewOf({ can_commit: false, counts: null, rows: [], reviewed: null, errors: [{ record: 4, column: 1, message: "Bad." }] }));
    expect(footer()).toEqual(["Cancel", "Back", "Choose corrected file…"]);
  });

  it("leaves at once for the page it was opened from when nothing is chosen yet", async () => {
    openedFromTheAccount();
    const confirm = vi.spyOn(window, "confirm");
    render(<ImportBalances id={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/accounts/7"));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks first once a file is chosen, stays when the person says so, and leaves when they agree", async () => {
    openedFromTheAccount();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await toMap();
    fireEvent.change(useOf("Note"), { target: { value: "ignore" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Nothing has been imported"));
    expect(window.location.pathname).toBe("/accounts/7/import");
    expect(useOf("Note").value).toBe("ignore");                                // still there, with the choice

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/accounts/7"));
    expect(confirm).toHaveBeenCalledTimes(2);                                  // once for each press, never twice for one
  });

  it("goes to the account when there is no earlier page of the app", async () => {
    window.history.replaceState({ idx: 0 }, "", "/accounts/7/import");
    render(<ImportBalances id={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(window.location.pathname).toBe("/accounts/7");
  });

  it("cannot be pressed while the import is being written", async () => {
    await toReview();
    vi.mocked(commitImport).mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    await screen.findByRole("button", { name: "Importing…" });
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Back" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("is Exit once the import is written: no question, and back to the page it was opened from", async () => {
    openedFromTheAccount();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await toReview();
    vi.mocked(commitImport).mockResolvedValue({ added: 2, updated: 0, unchanged: 0, skipped: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    fireEvent.click(await screen.findByRole("button", { name: "Exit" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/accounts/7"));
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();      // there is nothing left to cancel
  });
});

describe("Import: leaving", () => {
  it("asks before leaving once a file is chosen, and lets the person stay", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ImportBalances id={7} />);
    await screen.findByText("Choose a CSV file");
    expect(navigate("/accounts")).toBe(true);                                // nothing to lose yet
    window.history.replaceState(null, "", "/accounts/7/import");
    expect(confirm).not.toHaveBeenCalled();

    vi.mocked(fetchImportRead).mockResolvedValue(readOf());
    pick();
    await screen.findByText(/Tell Northstar what each column holds/);
    expect(navigate("/accounts")).toBe(false);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Nothing has been imported"));
    expect(window.location.pathname).toBe("/accounts/7/import");
  });

  it("does not ask once the import is done", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await toReview();
    vi.mocked(commitImport).mockResolvedValue({ added: 2, updated: 0, unchanged: 0, skipped: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Import 2 balances" }));
    await screen.findByText("Imported from statement.csv.");
    expect(navigate("/accounts/7")).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("the currency note on the review", () => {
  it("shows what in the file names another currency, and still lets the import go on", async () => {
    const note = "The 'Currency' column says EUR, and this account is in USD. Nothing is converted: every amount is read as USD.";
    await toReview(reviewOf({ notes: [note] }));
    expect(screen.getByRole("status", { name: "" }).textContent).toBe(note);
    expect((screen.getByRole("button", { name: /Import/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("says nothing when the file agrees with the account", async () => {
    await toReview(reviewOf({ notes: [] }));
    expect(document.querySelector(".notice.warn")).toBeNull();
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type CurrencyPageData } from "./api";
import { CurrencyPage } from "./CurrencyPage";
import { setLocale } from "./locale";
import { formatRate } from "./money";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fetchCurrency: vi.fn(), changeCurrency: vi.fn(), addRate: vi.fn(), correctRate: vi.fn(),
}));

import { addRate, changeCurrency, correctRate, fetchCurrency, RequestError } from "./api";

const rate = (id: number, date: string, value: string, over = {}) => ({
  id, date, rate: value, source: "manual", changed: date, until: null as string | null, ...over,
});

const page = (over: Partial<CurrencyPageData> = {}): CurrencyPageData => ({
  code: "EUR", name: "Euro", minor_units: 2, is_enabled: true, is_system: false, system_code: "USD", rates_start: "2020-01-01",
  default_rates_start: "2000-01-01", account_count: 3, open_account_count: 2, can_add_rates: true,
  rates: [rate(3, "2026-05-12", "1.0840"), rate(2, "2026-05-05", "1.0815", { until: "2026-05-12" }),
          rate(1, "2026-05-01", "1.0850", { until: "2026-05-05" })],
  stale: null, fetch: null, today: "2026-06-03", ...over,
});

afterEach(() => {
  cleanup();
  setLocale(null);
  vi.resetAllMocks();
});

const open = async (data: CurrencyPageData = page()) => {
  vi.mocked(fetchCurrency).mockResolvedValue(data);
  render(<CurrencyPage code={data.code} />);
  await screen.findByRole("heading", { level: 1 });
};

describe("the currency page", () => {
  it("shows the currency, whether it is enabled, when its rates start and its rates newest first", async () => {
    await open();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("EUR · Euro");
    expect(screen.getByRole("switch", { name: "Enabled" }).getAttribute("aria-checked")).toBe("true");
    expect((screen.getByLabelText("Rates start") as HTMLInputElement).value).toBe("2020-01-01");
    expect((screen.getByLabelText("Rates start") as HTMLInputElement).disabled).toBe(false);
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent));
    expect(rows).toEqual([
      ["May 12, 2026", "1.0840", "Manual", "May 12, 2026", "Correct"],
      ["May 5, 2026", "1.0815", "Manual", "May 5, 2026", "Correct"],
      ["May 1, 2026", "1.0850", "Manual", "May 1, 2026", "Correct"]]);
    expect(screen.getByText("1 EUR = USD")).toBeTruthy();
    expect(screen.getByText(/The 3 existing accounts keep working and still need rates/)).toBeTruthy();
  });

  it("says, when the first rate is later than the start date, which dates have none", async () => {
    await open();
    expect(screen.getByText(/Rates start May 1, 2026. Nothing from Jan 1, 2020 to Apr 30, 2026/)).toBeTruthy();
    cleanup();
    await open(page({ rates_start: "2026-05-01" }));
    expect(screen.queryByText(/Nothing from/)).toBeNull();
  });

  describe("the automatic fetch", () => {
    const run = (over = {}) => ({ date: "2026-06-03", time: "18:00", outcome: "succeeded" as const, detail: "Completed.", ...over });
    const fetchOf = (over = {}) => ({ time: "18:00", zone: "America/Chicago", last_run: run(), ...over });

    it("says when it runs, in which zone, from where, and that the last run succeeded", async () => {
      await open(page({ fetch: fetchOf() }));
      expect(screen.getByText("Rate source")).toBeTruthy();
      expect(screen.getByText(/Fetched daily at 18:00 \(America\/Chicago\) from Frankfurter/)).toBeTruthy();
      expect(screen.getByText("Last run: today, 18:00, succeeded.")).toBeTruthy();
      expect(screen.getByRole("link", { name: "Change the time" }).getAttribute("href")).toBe("/system-properties");
      expect(screen.queryByText(/\+\d/)).toBeNull();                   // no counts by currency
    });

    it("names the day of an older run in the person's format", async () => {
      await open(page({ fetch: fetchOf({ last_run: run({ date: "2026-06-01", time: "18:02" }) }) }));
      expect(screen.getByText("Last run: Jun 1, 2026, 18:02, succeeded.")).toBeTruthy();
    });

    it("shows a failed run in red with Northstar's message and when it runs again", async () => {
      await open(page({ fetch: fetchOf({ last_run: run({ outcome: "failed", detail: "Could not complete: Gave up after 4 tries: The rate provider did not answer." }) }) }));
      const line = screen.getByText(/^Last run:/);
      expect(line.textContent).toBe("Last run: today, 18:00, failed. Could not complete: Gave up after 4 tries: The rate provider did not answer. It runs again tomorrow at 18:00.");
      expect(line.className).toContain("bad");
    });

    it("says an interrupted run was interrupted, and that it runs again at the time when the run was not today", async () => {
      await open(page({ fetch: fetchOf({ last_run: run({ date: "2026-06-02", outcome: "abandoned", detail: "Abandoned: its lock expired before it finished." }) }) }));
      expect(screen.getByText(/^Last run:/).textContent).toBe("Last run: Jun 2, 2026, 18:00, was interrupted. Abandoned: its lock expired before it finished. It runs again at 18:00.");
    });

    it("says nothing has run and where the first run starts", async () => {
      await open(page({ fetch: fetchOf({ last_run: null }) }));
      expect(screen.getByText("No run yet. The first run fetches rates from the start date, Jan 1, 2020.")).toBeTruthy();
    });

    it("says a run is going on", async () => {
      await open(page({ fetch: fetchOf({ last_run: run({ outcome: "running", detail: null }) }) }));
      expect(screen.getByText("Running now. It started at 18:00.")).toBeTruthy();
    });

    it("says automatic fetching is off when no time is set, and links to set one", async () => {
      await open(page({ fetch: fetchOf({ time: null }) }));
      expect(screen.getByText("Rates are entered by hand. Automatic fetching is off.")).toBeTruthy();
      expect(screen.getByRole("link", { name: "Set a time" }).getAttribute("href")).toBe("/system-properties");
      expect(screen.queryByText(/Last run/)).toBeNull();
    });

    it("is not shown when the page has none, as for the system currency", async () => {
      await open(page({ fetch: null }));
      expect(screen.queryByText("Rate source")).toBeNull();
    });

    it("names Frankfurter as the source of a fetched rate and Manual for a typed one", async () => {
      await open(page({ rates: [rate(2, "2026-06-03", "1.1219", { source: "provider" }), rate(1, "2026-06-02", "1.1000")] }));
      const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => r.querySelectorAll("td")[2].textContent);
      expect(rows).toEqual(["Frankfurter", "Manual"]);
    });
  });

  it("warns that the rates are stale, with the days and the threshold", async () => {
    await open(page({ stale: { last_date: "2026-05-12", days: 22, threshold: 14 } }));
    expect(screen.getByText("Last rate was 22 days ago (May 12, 2026). Rates are stale after 14 days.")).toBeTruthy();
  });

  it("writes rates and dates in the person's own format", async () => {
    setLocale({ tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".", date_template: "{day2}.{month2}.{year}",
      currency_position: "suffix", currency_code_spacing: " " });
    await open(page({ rates: [rate(1, "2026-05-01", "1234.5000")] }));
    const cells = [...screen.getByRole("table").querySelectorAll("tbody td")].map((c) => c.textContent);
    expect(cells.slice(0, 2)).toEqual(["01.05.2026", "1.234,5000"]);
    expect(formatRate("0.000039")).toBe("0,000039");
  });

  it("shows a currency that is off with no start date box (the default is named in the text), no Add rate button and a way to switch it on", async () => {
    await open(page({ is_enabled: false, rates_start: null, can_add_rates: false, rates: [], account_count: 0, open_account_count: 0 }));
    expect(screen.getByRole("switch", { name: "Enabled" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByLabelText("Rates start")).toBeNull();          // the date is changed once the currency is on
    expect(screen.queryByRole("button", { name: "Add rate" })).toBeNull();
    expect(screen.getByText("Switch on EUR to add rates.")).toBeTruthy();
    expect(screen.getByText(/Switch on to allow new accounts in EUR. Its rates start from Jan 1, 2000, which can be changed once it is on. An account's currency is permanent./)).toBeTruthy();
  });
});

describe("switching on and off", () => {
  it("saves at once, with the date the box shows, and shows what the server answers", async () => {
    const off = page({ is_enabled: false, rates_start: null, can_add_rates: false, rates: [], account_count: 0 });
    await open(off);
    vi.mocked(changeCurrency).mockResolvedValue(page({ rates: [], rates_start: "2000-01-01" }));
    fireEvent.click(screen.getByRole("switch", { name: "Enabled" }));
    await waitFor(() => expect(changeCurrency).toHaveBeenCalledWith("EUR", { is_enabled: true, rates_start: "2000-01-01" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Enabled" }).getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByRole("button", { name: "Add rate" })).toBeTruthy();
  });

  it("frees the switch once a change is saved, so it can be changed again without reloading", async () => {
    await open();
    vi.mocked(changeCurrency).mockResolvedValueOnce(page({ is_enabled: false })).mockResolvedValueOnce(page());
    const toggle = () => screen.getByRole("switch", { name: "Enabled" }) as HTMLButtonElement;
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("false"));
    expect(toggle().disabled).toBe(false);
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle().getAttribute("aria-checked")).toBe("true"));
    expect(toggle().disabled).toBe(false);
    expect(changeCurrency).toHaveBeenCalledTimes(2);
  });

  it("frees the switch after a refusal too", async () => {
    await open();
    vi.mocked(changeCurrency).mockRejectedValue(new RequestError("No.", {}, 422));
    fireEvent.click(screen.getByRole("switch", { name: "Enabled" }));
    await screen.findByRole("alert");
    expect((screen.getByRole("switch", { name: "Enabled" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("switches off with no question, and says what that does", async () => {
    await open();
    vi.mocked(changeCurrency).mockResolvedValue(page({ is_enabled: false }));
    fireEvent.click(screen.getByRole("switch", { name: "Enabled" }));
    await waitFor(() => expect(changeCurrency).toHaveBeenCalledWith("EUR", { is_enabled: false, rates_start: "2020-01-01" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the server's refusal and leaves the switch as it was", async () => {
    await open();
    vi.mocked(changeCurrency).mockRejectedValue(new RequestError("Enter the date rates start from.", {}, 422));
    fireEvent.click(screen.getByRole("switch", { name: "Enabled" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the date rates start from.");
    expect(screen.getByRole("switch", { name: "Enabled" }).getAttribute("aria-checked")).toBe("true");
  });

  it("saves a new start date when it is chosen, and refuses an empty one without asking the server", async () => {
    await open();
    vi.mocked(changeCurrency).mockResolvedValue(page({ rates_start: "2018-05-06" }));
    fireEvent.change(screen.getByLabelText("Rates start"), { target: { value: "2018-05-06" } });
    await waitFor(() => expect(changeCurrency).toHaveBeenCalledWith("EUR", { rates_start: "2018-05-06" }));
    vi.mocked(changeCurrency).mockClear();
    fireEvent.change(screen.getByLabelText("Rates start"), { target: { value: "" } });
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the date rates start from.");
    expect(changeCurrency).not.toHaveBeenCalled();
  });

  it("does not let the system currency be switched, and says it needs no rates", async () => {
    await open(page({ code: "USD", name: "US Dollar", is_system: true, system_code: "USD", rates_start: null, can_add_rates: false, rates: [] }));
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByLabelText("Rates start")).toBeNull();
    expect(screen.getByText(/USD is the system currency, so it is always enabled and every total is in USD. It needs no rates./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add rate" })).toBeNull();
  });
});

describe("adding and correcting a rate", () => {
  it("adds a rate in a dialog, with today as the date, and closes it when the server accepts", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    const dialog = screen.getByRole("dialog", { name: "Add rate" });
    expect((within(dialog).getByLabelText("Date") as HTMLInputElement).value).toBe("2026-06-03");
    fireEvent.change(within(dialog).getByLabelText("Rate: 1 EUR in USD"), { target: { value: "1.0900" } });
    vi.mocked(addRate).mockResolvedValue(page({ rates: [rate(4, "2026-06-03", "1.0900"), ...page().rates] }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add rate" }));
    await waitFor(() => expect(addRate).toHaveBeenCalledWith("EUR", { date: "2026-06-03", rate: "1.0900" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getAllByRole("row")).toHaveLength(5);
  });

  it("keeps the dialog open with the server's reason when a rate is refused", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Rate: 1 EUR in USD"), { target: { value: "2" } });
    vi.mocked(addRate).mockRejectedValue(new RequestError("A rate for Jun 3, 2026 already exists. Use Correct to change it.", {}, 422));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add rate" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("A rate for Jun 3, 2026 already exists. Use Correct to change it.");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("closes the dialog on Cancel without saving", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(addRate).not.toHaveBeenCalled();
  });

  it("corrects a rate: its date is shown and fixed, and what it changes is stated", async () => {
    await open();
    fireEvent.click(within(screen.getAllByRole("row")[3]).getByRole("button", { name: "Correct" }));          // the 1 May rate
    const dialog = screen.getByRole("dialog", { name: "Correct rate" });
    expect(within(dialog).queryByLabelText("Date")).toBeNull();
    expect(dialog.textContent).toContain("May 1, 2026");
    expect(dialog.textContent).toContain("This changes net worth from May 1, 2026 until the next stored rate on May 5, 2026.");
    const box = within(dialog).getByLabelText("Rate: 1 EUR in USD") as HTMLInputElement;
    expect(box.value).toBe("1.0850");
    fireEvent.change(box, { target: { value: "1.09" } });
    vi.mocked(correctRate).mockResolvedValue(page());
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(correctRate).toHaveBeenCalledWith("EUR", 1, "1.09"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says a correction of the newest rate changes net worth from its date on, and shows the rate as typed in the person's format", async () => {
    setLocale({ tag: "de-DE", label: "German (Germany)", decimal_mark: ",", group_mark: ".", date_template: "{day2}.{month2}.{year}",
      currency_position: "suffix", currency_code_spacing: " " });
    await open();
    fireEvent.click(within(screen.getAllByRole("row")[1]).getByRole("button", { name: "Correct" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("This changes net worth from 12.05.2026 on.");
    expect((within(dialog).getByLabelText("Rate: 1 EUR in USD") as HTMLInputElement).value).toBe("1,0840");
  });
});

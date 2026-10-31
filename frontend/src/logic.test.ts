import { describe, expect, it } from "vitest";
import { addMonths, dayNumber, formatDate, isoFromDay } from "./dates";
import { centsToInput, formatCents, percentChange } from "./money";
import { PERIOD, RANGES, rangeStart } from "./ranges";

describe("dates", () => {
  it("counts days from 1970-01-01", () => {
    expect(dayNumber("1970-01-01")).toBe(0);
    expect(dayNumber("1970-01-02")).toBe(1);
    expect(dayNumber("1969-12-31")).toBe(-1);
    expect(dayNumber("2026-10-30") - dayNumber("2026-10-29")).toBe(1);
  });

  it("agrees with the built-in calendar on every day for 60 years, and round-trips", () => {
    // The test may use Date. The app code may not, so this checks the hand-written arithmetic.
    for (let ms = Date.UTC(1990, 0, 1); ms < Date.UTC(2050, 0, 1); ms += 86_400_000) {
      const iso = new Date(ms).toISOString().slice(0, 10);
      expect(dayNumber(iso)).toBe(ms / 86_400_000);
      expect(isoFromDay(ms / 86_400_000)).toBe(iso);
    }
  });

  it("formats a date without moving it (vite.config.ts runs these tests in a US timezone)", () => {
    expect(formatDate("2026-10-30")).toBe("Oct 30, 2026");
    expect(formatDate("2026-01-01")).toBe("Jan 1, 2026");
  });

  it("adds months and pulls a day past the end of the month back", () => {
    expect(addMonths("2026-10-30", -1)).toBe("2026-09-30");
    expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
    expect(addMonths("2028-03-31", -1)).toBe("2028-02-29");
    expect(addMonths("2026-01-15", -1)).toBe("2025-12-15");
    expect(addMonths("2026-10-30", -12)).toBe("2025-10-30");
    expect(addMonths("2026-02-28", -60)).toBe("2021-02-28");
  });
});

describe("money", () => {
  it("shows integer cents as dollars and cents", () => {
    expect(formatCents(0)).toBe("$0.00");
    expect(formatCents(5)).toBe("$0.05");
    expect(formatCents(123456)).toBe("$1,234.56");
    expect(formatCents(-5)).toBe("-$0.05");
    expect(formatCents(-123456)).toBe("-$1,234.56");
    expect(formatCents(12345678900)).toBe("$123,456,789.00");
  });

  it("has no percent change from a zero base, and uses the size of a negative base", () => {
    expect(percentChange(500, 0)).toBeNull();
    expect(percentChange(50, 1000)).toBe(5);
    expect(percentChange(-50, -1000)).toBe(-5);
  });
});

describe("ranges", () => {
  it("starts each range a calendar period back from the server's today", () => {
    expect(rangeStart("1M", "2026-10-30")).toBe("2026-09-30");
    expect(rangeStart("3M", "2026-10-30")).toBe("2026-07-30");
    expect(rangeStart("6M", "2026-10-30")).toBe("2026-04-30");
    expect(rangeStart("1Y", "2026-10-30")).toBe("2025-10-30");
    expect(rangeStart("5Y", "2026-10-30")).toBe("2021-10-30");
    expect(rangeStart("YTD", "2026-10-30")).toBe("2026-01-01");
  });

  it("clamps a month-end start the way the calendar does", () => {
    expect(rangeStart("1M", "2026-03-31")).toBe("2026-02-28");
    expect(rangeStart("1Y", "2028-02-29")).toBe("2027-02-28");
  });

  it("leaves ALL without a start, so the server begins at the first balance", () => {
    expect(rangeStart("ALL", "2026-10-30")).toBeUndefined();
  });

  it("gives every range a period, finer for short ranges", () => {
    expect(RANGES.map((r) => PERIOD[r])).toEqual(["day", "day", "week", "week", "week", "month", "month"]);
  });
});

describe("centsToInput", () => {
  it("gives plain text an amount box can start with", () => {
    expect(centsToInput(123456)).toBe("1234.56");
    expect(centsToInput(5)).toBe("0.05");
    expect(centsToInput(0)).toBe("0.00");
    expect(centsToInput(-2500)).toBe("-25.00");
    expect(centsToInput(100000000)).toBe("1000000.00");
  });
});

import { describe, expect, it } from "vitest";
import type { UpdateRow } from "./api";
import { baselineText, changedAmounts, changeFromLast, isTyped, rowState, summarize, valuesForDate } from "./updateLogic";

const row = (id: number, over: Partial<UpdateRow> = {}): UpdateRow => ({
  id, name: `Account ${id}`, class_name: "Asset", type_name: "Checking", stale_after_days: 35,
  last_date: "2026-10-01", last_cents: 100000, days_since: 30, stale: false, existing_cents: null, ...over,
});

describe("rows of the Update balances form", () => {
  it("starts with what is saved on the date, or nothing", () => {
    expect(baselineText(row(1))).toBe("");
    expect(baselineText(row(1, { existing_cents: 482310 }))).toBe("4823.10");
    expect(baselineText(row(1, { existing_cents: 0 }))).toBe("0.00");
  });

  it("calls a box typed when it differs from what is saved", () => {
    const saved = row(1, { existing_cents: 482310 });
    expect(isTyped(saved, "4823.10")).toBe(false);
    expect(isTyped(saved, "5000")).toBe(true);
    expect(isTyped(row(2), "")).toBe(false);
    expect(isTyped(row(2), "0")).toBe(true);
  });

  it("classifies a box as blank, invalid, new, replacing or the same", () => {
    const saved = row(1, { existing_cents: 482310 });
    expect(rowState(row(2), "  ").kind).toBe("blank");
    expect(rowState(row(2), "12,3x").kind).toBe("invalid");
    expect(rowState(row(2), "50")).toEqual({ kind: "new", cents: 5000 });
    expect(rowState(saved, "5,000")).toEqual({ kind: "replace", cents: 500000 });
    expect(rowState(saved, "4823.10")).toEqual({ kind: "same", cents: 482310 });
    expect(rowState(row(2), "0")).toEqual({ kind: "new", cents: 0 }); // a zero must be typed, and counts
  });

  it("shows the change from the last balance, and a falling liability as good", () => {
    expect(changeFromLast(row(1), 150000)).toEqual({ diff: 50000, good: true });
    expect(changeFromLast(row(1), 90000)).toEqual({ diff: -10000, good: false });
    const loan = row(2, { class_name: "Liability" });
    expect(changeFromLast(loan, 90000)).toEqual({ diff: -10000, good: true });
    expect(changeFromLast(loan, 110000)).toEqual({ diff: 10000, good: false });
    expect(changeFromLast(row(3, { last_cents: null }), 5)).toBeNull();
  });

  it("counts what a save would do", () => {
    const rows = [row(1, { existing_cents: 100 }), row(2, { existing_cents: 200 }), row(3), row(4), row(5)];
    const values = { 1: "5.00", 2: "2.00", 3: "10", 4: "x", 5: "" };
    expect(summarize(rows, values)).toEqual({ entered: 4, added: 1, replacing: 1, same: 1, invalid: 1 });
  });
});

describe("moving to another date", () => {
  const before = [row(1, { existing_cents: 482310 }), row(2, { existing_cents: 1250000 }), row(3)];
  const typedValues = { 1: "5000", 2: "12500.00", 3: "1200" }; // 1 and 3 typed, 2 is as saved
  const after = [row(1, { existing_cents: 111 }), row(2, { existing_cents: 222 }), row(3)];

  it("keeps typed rows and loads the saved amounts into the others", () => {
    expect(valuesForDate(before, typedValues, after, true)).toEqual({ 1: "5000", 2: "2.22", 3: "1200" });
  });

  it("clears the form to what the new date has saved", () => {
    expect(valuesForDate(before, typedValues, after, false)).toEqual({ 1: "1.11", 2: "2.22", 3: "" });
  });

  it("with nothing typed, keep and clear give the same form", () => {
    const untouched = { 1: "4823.10", 2: "12500.00", 3: "" };
    expect(valuesForDate(before, untouched, after, true)).toEqual(valuesForDate(before, untouched, after, false));
  });
});

describe("what a save sends", () => {
  const rows = [row(1, { existing_cents: 500000 }), row(2, { existing_cents: 1250000 }), row(3), row(4, { existing_cents: 184277 })];

  it("sends only the rows the person changed, never the prefilled ones", () => {
    // Rows 1, 2 and 4 are prefilled from what is saved on the date. Only row 3 was typed in.
    const values = { 1: "5000.00", 2: "12500.00", 3: "1000", 4: "1842.77" };
    expect(changedAmounts(rows, values)).toEqual({ 3: "1000" });
  });

  it("sends a prefilled row once its text is changed", () => {
    const values = { 1: "5000.00", 2: "13000", 3: "", 4: "1842.77" };
    expect(changedAmounts(rows, values)).toEqual({ 2: "13000" });
  });

  it("sends nothing for a row that was cleared, because a blank row is skipped", () => {
    expect(changedAmounts(rows, { 1: "", 2: "12500.00", 3: "", 4: "1842.77" })).toEqual({});
    expect(changedAmounts(rows, { 1: "   ", 2: "12500.00", 3: "", 4: "1842.77" })).toEqual({});
  });

  it("sends a typed zero, and the text exactly as typed so the server checks it", () => {
    expect(changedAmounts(rows, { 1: "5000.00", 2: "12500.00", 3: "0", 4: "1842.77" })).toEqual({ 3: "0" });
    expect(changedAmounts(rows, { 1: "12,3x", 2: "12500.00", 3: "", 4: "1842.77" })).toEqual({ 1: "12,3x" });
  });

  it("sends nothing when the form is as saved", () => {
    expect(changedAmounts(rows, { 1: "5000.00", 2: "12500.00", 3: "", 4: "1842.77" })).toEqual({});
  });
});

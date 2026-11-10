import { describe, expect, it } from "vitest";
import type { ListColumn } from "./api";
import { formatCell, formatScaled, isNumeric } from "./listFormat";
import { getLocale } from "./locale";

const column = (kind: ListColumn["kind"], scale: number | null = null): ListColumn =>
  ({ key: "k", label: "K", path_label: "K", kind, scale, linked: false, groupable: true });

describe("what a cell shows", () => {
  it("shows nothing for an empty value, so the list can draw its own dash", () => {
    for (const kind of ["text", "integer", "number", "decimal", "date", "timestamp", "yes_no", "choice", "amount"] as const) {
      expect(formatCell(column(kind), null)).toBeNull();
      expect(formatCell(column(kind), undefined)).toBeNull();
    }
  });

  it("writes whole numbers, numbers and text in the person's format", () => {
    expect(formatCell(column("integer"), 1234567)).toBe("1,234,567");
    expect(formatCell(column("integer"), 0)).toBe("0");
    expect(formatCell(column("number"), 2.25)).toBe("2.25");
    expect(formatCell(column("text"), "Test")).toBe("Test");
    expect(formatCell(column("choice"), "Open")).toBe("Open");
  });

  it("writes a decimal held as a whole number with its scale, never rounded", () => {
    expect(formatScaled(1999, 2)).toBe("19.99");
    expect(formatScaled(-250, 2)).toBe("-2.50");
    expect(formatScaled(5, 2)).toBe("0.05");
    expect(formatScaled(-5, 3)).toBe("-0.005");
    expect(formatScaled(1234567, 0)).toBe("1,234,567");
    expect(formatCell(column("decimal", 2), 1999)).toBe("19.99");
  });

  it("writes an amount with its own currency, whatever the scale, so it reads without the currency column", () => {
    expect(formatCell(column("amount"), { value: 123456, scale: 2, unit: "USD" })).toBe("$1,234.56");
    const gap = getLocale().currency_code_spacing;                            // the locale's own space between a code and the number
    expect(formatCell(column("amount"), { value: 123456, scale: 2, unit: "EUR" })).toBe(`EUR${gap}1,234.56`);
    expect(formatCell(column("amount"), { value: 1234, scale: 0, unit: "JPY" })).toBe(`JPY${gap}1,234`);
    expect(formatCell(column("amount"), { value: -80, scale: 2, unit: "USD" })).toBe("-$0.80");
    expect(formatCell(column("amount"), { value: 1999, scale: 2, unit: null })).toBe("19.99");
  });

  it("writes a date, a timestamp as its UTC date, and a flag as Yes or No", () => {
    expect(formatCell(column("date"), "2026-01-31")).toBe("Jan 31, 2026");
    expect(formatCell(column("timestamp"), "2026-01-31T23:30:00Z")).toBe("Jan 31, 2026");
    expect(formatCell(column("yes_no"), 1)).toBe("Yes");
    expect(formatCell(column("yes_no"), 0)).toBe("No");
  });

  it("lines numbers up on the right and nothing else", () => {
    expect(["integer", "number", "decimal", "amount"].every((kind) => isNumeric(column(kind as ListColumn["kind"])))).toBe(true);
    expect(["text", "date", "timestamp", "yes_no", "choice"].some((kind) => isNumeric(column(kind as ListColumn["kind"])))).toBe(false);
  });
});

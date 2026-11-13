// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initialValues, ParameterControls, parametersFor, problems } from "./parameters";
import type { ReportDefinition, ReportParameter } from "./types";

afterEach(cleanup);

const date = (key: string, label: string, rules: ReportParameter["rules"] = [], value = "2026-11-11"): ReportParameter =>
  ({ key, label, kind: "date", default: value, choices: [], minimum: null, maximum: null, rules });
const definition = (parameters: ReportParameter[]): ReportDefinition =>
  ({ key: "probe", title: "Probe", description: "A probe.", today: "2026-11-11", parameters, sections: [], filters: { enabled: false } });

const PAIR = definition([date("opening", "Opening", [], "2025-11-11"), date("closing", "Closing", [{ rule: "not_future" }, { rule: "after", other: "opening" }])]);
const RANGE = definition([date("from", "From", [], "2026-01-01"), date("to", "To", [{ rule: "on_or_after", other: "from" }, { rule: "not_future" }])]);
const MIXED = definition([
  { key: "interval", label: "Interval", kind: "choice", default: "month", choices: [{ value: "month", label: "Month" }, { value: "week", label: "Week" }], minimum: null, maximum: null, rules: [] },
  { key: "count", label: "Count", kind: "integer", default: 5, choices: [], minimum: 1, maximum: 10, rules: [] },
]);

describe("the parameters of a report", () => {
  it("start at the defaults the server resolved, as text, and are sent as typed values with every parameter named", () => {
    expect(initialValues(PAIR)).toEqual({ opening: "2025-11-11", closing: "2026-11-11" });
    expect(initialValues(MIXED)).toEqual({ interval: "month", count: "5" });
    expect(parametersFor(MIXED, initialValues(MIXED))).toEqual({ interval: "month", count: 5 });
    expect(parametersFor(PAIR, initialValues(PAIR))).toEqual({ opening: "2025-11-11", closing: "2026-11-11" });
  });

  it("have nothing wrong at their defaults", () => {
    for (const d of [PAIR, RANGE, MIXED]) expect(Object.values(problems(d, initialValues(d))).every((p) => p === null)).toBe(true);
  });

  it("refuse a date that is not a real day, or is not there yet, and say so", () => {
    for (const bad of ["", "2026-02-30", "26-01-01", "next week"]) expect(problems(PAIR, { ...initialValues(PAIR), closing: bad }).closing).toBe("Choose a real date.");
  });

  it("refuse a date in the future, by the server's own today and not the browser's", () => {
    expect(problems(PAIR, { opening: "2025-11-11", closing: "2026-11-12" }).closing).toMatch(/earlier date/);
    expect(problems(PAIR, { opening: "2025-11-11", closing: "2026-11-11" }).closing).toBeNull();
  });

  it("hold a pair strictly in order: the closing day must be after the opening day", () => {
    expect(problems(PAIR, { opening: "2026-06-30", closing: "2026-06-30" }).closing).toBe("Closing must be after Opening.");
    expect(problems(PAIR, { opening: "2026-07-01", closing: "2026-06-30" }).closing).toBe("Closing must be after Opening.");
    expect(problems(PAIR, { opening: "2026-06-29", closing: "2026-06-30" }).closing).toBeNull();
  });

  it("hold an inclusive range in order but allow one day: the same day is a range", () => {
    expect(problems(RANGE, { from: "2026-06-30", to: "2026-06-30" }).to).toBeNull();
    expect(problems(RANGE, { from: "2026-07-01", to: "2026-06-30" }).to).toBe("To must be on or after From.");
  });

  it("do not blame a date for an order that cannot be judged because the other is not a date yet", () => {
    expect(problems(PAIR, { opening: "2026-0", closing: "2026-06-30" }).closing).toBeNull();
    expect(problems(PAIR, { opening: "2026-0", closing: "2026-06-30" }).opening).toBe("Choose a real date.");
  });

  it("accept only one of a choice's options", () => {
    expect(problems(MIXED, { interval: "year", count: "5" }).interval).toBe("Choose one of the options.");
    expect(problems(MIXED, { interval: "week", count: "5" }).interval).toBeNull();
  });

  it("accept only a whole number inside the limits", () => {
    for (const bad of ["", "five", "1.5", "2e1", "--1"]) expect(problems(MIXED, { interval: "month", count: bad }).count).toBe("Enter a whole number.");
    expect(problems(MIXED, { interval: "month", count: "0" }).count).toBe("Enter a number from 1 to 10.");
    expect(problems(MIXED, { interval: "month", count: "11" }).count).toBe("Enter a number from 1 to 10.");
    expect(problems(MIXED, { interval: "month", count: " 7 " }).count).toBeNull();
    const open = definition([{ key: "n", label: "N", kind: "integer", default: 3, choices: [], minimum: 2, maximum: null, rules: [] }]);
    expect(problems(open, { n: "1" }).n).toBe("Enter a number of 2 or more.");
    const capped = definition([{ key: "n", label: "N", kind: "integer", default: 3, choices: [], minimum: null, maximum: 4, rules: [] }]);
    expect(problems(capped, { n: "5" }).n).toBe("Enter a number of 4 or less.");
  });
});

describe("the controls", () => {
  it("are one labelled control for each parameter, a date box, a list of options or a number box, in the report's order", () => {
    render(<ParameterControls definition={MIXED} values={initialValues(MIXED)} errors={{ interval: null, count: null }} onChange={() => {}} />);
    expect((screen.getByLabelText("Interval") as HTMLSelectElement).value).toBe("month");
    expect([...(screen.getByLabelText("Interval") as HTMLSelectElement).options].map((o) => o.textContent)).toEqual(["Month", "Week"]);
    expect((screen.getByLabelText("Count") as HTMLInputElement).value).toBe("5");
    cleanup();
    render(<ParameterControls definition={PAIR} values={initialValues(PAIR)} errors={{ opening: null, closing: null }} onChange={() => {}} />);
    expect((screen.getByLabelText("Opening") as HTMLInputElement).type).toBe("date");
    expect((screen.getByLabelText("Closing") as HTMLInputElement).value).toBe("2026-11-11");
  });

  it("say what was changed, by key, and mark the one with a problem", () => {
    const onChange = vi.fn();
    render(<ParameterControls definition={PAIR} values={initialValues(PAIR)} errors={{ opening: null, closing: "Closing must be after Opening." }} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Opening"), { target: { value: "2026-01-01" } });
    expect(onChange).toHaveBeenCalledWith("opening", "2026-01-01");
    expect(screen.getByLabelText("Closing").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText("Opening").getAttribute("aria-invalid")).toBeNull();
  });
});

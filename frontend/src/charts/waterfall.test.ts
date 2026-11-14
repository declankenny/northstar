import { describe, expect, it } from "vitest";
import { axisRange, type Bar, bridgeBars, extent, niceStep, type Range, scaleOption, type StepNode, waterfallOption, type Words } from "./waterfall";
import type { ChartTheme } from "./theme";

const step = (id: string, opening: number, closing: number, note?: string): StepNode => ({ id, name: id.toUpperCase(), value: closing - opening, opening, closing, note });

const THEME: ChartTheme = {
  text: "#111111", muted: "#999999", surface: "#ffffff", border: "#cccccc", positive: "#00aa00", negative: "#aa0000", accent: "#0000aa", series: [],
};
const WORDS: Words = {
  amount: (n) => `$${n}`, change: (n) => `${n > 0 ? "+" : ""}$${n}`, short: (n) => `s${n}`, shortChange: (n) => `${n > 0 ? "+" : ""}s${n}`, whole: (n) => `w${n}`,
};

describe("the bars of a bridge", () => {
  it("are an opening total, a step from the running total for each node in the order given, and a closing total", () => {
    const bars = bridgeBars([step("a", 100, 150, "2 accounts"), step("b", 60, 40), step("c", 0, 5)]);
    expect(bars.map((b) => [b.id, b.kind, b.start, b.end, b.value])).toEqual([
      ["opening", "total", 0, 160, 160], ["a", "step", 160, 210, 50], ["b", "step", 210, 190, -20], ["c", "step", 190, 195, 5], ["closing", "total", 0, 195, 195],
    ]);
    expect(bars[1].note).toBe("2 accounts");
  });

  it("start and end at the whole the report gives, which is more than the steps add up to when something did not change", () => {
    const bars = bridgeBars([step("a", 100, 150), step("b", 60, 40)], { opening: 1_000, closing: 1_030 });
    expect(bars.map((b) => [b.id, b.start, b.end])).toEqual([["opening", 0, 1_000], ["a", 1_000, 1_050], ["b", 1_050, 1_030], ["closing", 0, 1_030]]);
  });

  it("have equal totals and no steps for nothing, and a closing total that is the running total at the end", () => {
    const bars = bridgeBars([]);
    expect(bars.map((b) => b.id)).toEqual(["opening", "closing"]);
    expect(bars.map((b) => b.end)).toEqual([0, 0]);
    const some = bridgeBars([step("a", -300, -100), step("b", 50, 25)]);
    expect(some[some.length - 1].end).toBe(some[some.length - 2].end);
  });

  it("go below zero and back as the running total does", () => {
    const bars = bridgeBars([step("a", 100, 0), step("b", 0, -250), step("c", 0, 400)]);
    expect(bars.slice(1, -1).map((b) => [b.start, b.end])).toEqual([[100, 0], [0, -250], [-250, 150]]);
  });
});

describe("the distance between lines of the scale", () => {
  it("is 1, 2 or 5 times a power of ten that is not below what was asked for, and at least 1", () => {
    expect(niceStep(0)).toBe(1);
    expect(niceStep(0.4)).toBe(1);
    expect(niceStep(1.5)).toBe(2);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(7)).toBe(10);
    expect(niceStep(1_300_000)).toBe(2_000_000);
    expect(niceStep(5_000_000)).toBe(5_000_000);
    expect(niceStep(5_000_001)).toBe(10_000_000);
  });
});

describe("the scale", () => {
  const range = (...steps: StepNode[]) => axisRange(bridgeBars(steps));

  it("starts zoomed in, below the lowest the running total reaches and not at zero", () => {
    const r = range(step("a", 17_000_000, 18_000_000), step("b", 6_900_000, 6_200_000));         // the running total is 23.9M, 24.9M, 24.2M
    expect(r.min).toBeGreaterThan(0);
    expect(r.min).toBeLessThan(23_900_000);
  });

  it("ends on a round number with room above the tallest bar for its label, and every line is a multiple of the distance", () => {
    const r = range(step("a", 17_000_000, 18_000_000), step("b", 6_900_000, 6_200_000));
    expect(r.max).toBeGreaterThanOrEqual(24_900_000 + 0.3 * 1_000_000);
    expect(r.min % r.step).toBe(0);
    expect(r.max % r.step).toBe(0);
  });

  it("has lines at 1, 2 or 5 times a power of ten, whatever the amounts", () => {
    for (const [a, b] of [[17_000_000, 18_000_000], [123, 177], [4_999_999, 5_300_000], [10, 12], [900_000_000, 910_000_000]]) {
      expect(String(range(step("a", a, b)).step), `${a} to ${b}`).toMatch(/^[125]0*$/);
    }
  });

  it("holds zero when the running total goes below it, and every level of the bridge is inside it", () => {
    const bars = bridgeBars([step("a", 100, 0), step("b", 0, -250), step("c", 0, 400)]);
    const r = axisRange(bars);
    expect(r.min).toBeLessThan(-250);
    expect(r.max).toBeGreaterThan(150);
    for (const b of bars) for (const level of [b.start, b.end]) {
      if (b.kind === "total" && level === 0) continue;
      expect(level).toBeGreaterThanOrEqual(r.min);
      expect(level).toBeLessThanOrEqual(r.max);
    }
  });

  it("has room above zero for the labels of totals that hang from it, when net worth is below zero", () => {
    const r = range(step("a", -900, -500), step("b", -100, -60));
    expect(r.max).toBeGreaterThan(0);
    expect(r.max).toBeGreaterThanOrEqual(0.3 * 1_000);                          // a share of the whole span, as above the highest bar
  });

  it("does not cross zero when the running total stays above it, even when it comes close", () => {
    expect(range(step("a", 1_000, 1_300), step("b", 200, 150)).min).toBeGreaterThanOrEqual(0);
  });

  it("is a usable scale for nothing, for steps that cancel, and for one step", () => {
    expect(axisRange(bridgeBars([]))).toEqual({ min: 0, max: 1, step: 1 });
    const flat = range(step("a", 100, 150), step("b", 50, 0));
    expect(flat.max).toBeGreaterThan(flat.min);
    expect(range(step("a", 0, 40)).max).toBeGreaterThan(40);
  });
});

describe("where a bar is drawn", () => {
  const r: Range = { min: 1_000, max: 2_000, step: 250 };
  const total: Bar = { id: "t", name: "T", kind: "total", start: 0, end: 1_500, value: 1_500 };

  it("grows from zero, or from the nearest edge of the scale when it does not hold zero", () => {
    expect(extent({ ...total, end: 300, value: 300 }, { min: -500, max: 500, step: 250 })).toEqual({ low: 0, high: 300 });
    expect(extent({ ...total, end: 1_300, value: 1_300 }, r)).toEqual({ low: 1_000, high: 1_300 });
    expect(extent({ ...total, end: -600, value: -600 }, { min: -900, max: -300, step: 100 })).toEqual({ low: -600, high: -300 });
  });

  it("for a total on a zoomed scale starts at the bottom of the chart, and for a step is from where it started to where it ended", () => {
    expect(extent(total, r)).toEqual({ low: 1_000, high: 1_500 });
    expect(extent({ id: "s", name: "S", kind: "step", start: 1_800, end: 1_200, value: -600 }, r)).toEqual({ low: 1_200, high: 1_800 });
  });

  it("for a total below zero hangs from zero, and a step that crosses zero covers both sides of it", () => {
    const wide: Range = { min: -500, max: 500, step: 250 };
    expect(extent({ ...total, end: -300, value: -300 }, wide)).toEqual({ low: -300, high: 0 });
    expect(extent({ id: "s", name: "S", kind: "step", start: 200, end: -100, value: -300 }, wide)).toEqual({ low: -100, high: 200 });
  });

  it("is kept inside the scale", () => {
    expect(extent({ id: "s", name: "S", kind: "step", start: 500, end: 9_000, value: 8_500 }, r)).toEqual({ low: 1_000, high: 2_000 });
  });
});

describe("the option", () => {
  const bars = bridgeBars([step("a", 100, 150, "2 accounts"), step("b", 60, 40)]);
  const r = axisRange(bars);
  const option = waterfallOption(bars, r, THEME, WORDS) as never as {
    xAxis: { data: string[] }; yAxis: { min: number; max: number; interval: number; axisLabel: { show: boolean } };
    series: { type: string; data: { id: string }[] }[]; tooltip: { formatter: (p: unknown) => string };
  };

  it("names each bar under it, and has the same scale as the scale column that sits beside it", () => {
    expect(option.xAxis.data).toEqual(["Opening balance", "A", "B", "Closing balance"]);
    const scale = scaleOption(r, THEME, WORDS) as never as { yAxis: { min: number; max: number; interval: number; axisLabel: { show?: boolean; formatter: (v: number) => string } } };
    expect([scale.yAxis.min, scale.yAxis.max, scale.yAxis.interval]).toEqual([option.yAxis.min, option.yAxis.max, option.yAxis.interval]);
    expect(option.yAxis.axisLabel.show).toBe(false);
    expect(scale.yAxis.axisLabel.formatter(1_000)).toBe("s1000");
  });

  it("draws one custom series, one item a bar", () => {
    expect(option.series).toHaveLength(1);
    expect(option.series[0].type).toBe("custom");
    expect(option.series[0].data.map((d) => d.id)).toEqual(["opening", "a", "b", "closing"]);
  });

  it("tells a step's change, its note and what the total is, as class-only markup", () => {
    const tip = (id: string) => option.tooltip.formatter({ data: { id } });
    expect(tip("a")).toContain("+$50");
    expect(tip("a")).toContain("2 accounts");
    expect(tip("b")).toContain("$-20");
    expect(tip("opening")).toContain("Net worth");
    expect(tip("opening")).toContain("$160");
    expect(tip("nothing")).toBe("");
    expect(tip("a")).not.toMatch(/\bstyle\s*=/i);
  });
});

import type { EChartsCoreOption } from "./echarts";
import type { ChartTheme } from "./theme";
import { tooltipOption } from "./tooltip";

/** One step of a bridge: a group of the report with its value at each end of the period and its change (`value`, so closing minus
 *  opening). The report works these out and checks them; the chart only draws them. */
export type StepNode = { id: string; name: string; value: number; opening: number; closing: number; note?: string };

/** A bar of the waterfall: a total (from the baseline up or down to its amount) or a step (from where the running total was to where it is
 *  now). `start` and `end` are amounts, and a step's `value` is its signed change. */
export type Bar = { id: string; name: string; kind: "total" | "step"; start: number; end: number; value: number; note?: string };

/** What the opening and closing bars are called. */
export const OPENING = { id: "opening", name: "Opening balance" };
export const CLOSING = { id: "closing", name: "Closing balance" };

/** The whole at each end of the period. The steps are only what changed, so they do not add up to it: what did not change is in the whole
 *  and in no step. The report says what the whole is, and the steps' changes add up to the difference. */
export type Whole = { opening: number; closing: number };

/** The bars of a bridge, in the order the report gave its steps: the opening total, a step each from the running total, and the closing
 *  total. When the report does not give the whole, it is the sum of the steps' own amounts (everything in it changed). */
export function bridgeBars(nodes: StepNode[], whole?: Whole): Bar[] {
  const opening = whole?.opening ?? nodes.reduce((total, n) => total + n.opening, 0);
  const closing = whole?.closing ?? nodes.reduce((total, n) => total + n.closing, 0);
  let running = opening;
  const steps: Bar[] = nodes.map((n) => {
    const bar: Bar = { id: n.id, name: n.name, kind: "step", start: running, end: running + n.value, value: n.value, note: n.note };
    running += n.value;
    return bar;
  });
  return [{ ...OPENING, kind: "total", start: 0, end: opening, value: opening }, ...steps, { ...CLOSING, kind: "total", start: 0, end: closing, value: closing }];
}

/** The scale: the lowest and highest amount it shows and the distance between its lines, in minor units. */
export type Range = { min: number; max: number; step: number };

/** The nearest of 1, 2 or 5 times a power of ten that is not below `raw` (and at least 1), so a scale's lines fall on round numbers. */
export function niceStep(raw: number): number {
  if (!(raw > 1)) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
}

/** The scale of the waterfall. It starts zoomed in, not at zero: it runs from a little below the lowest the running total reaches to a
 *  little above the highest, so the steps are big enough to read. It still holds zero when the running total goes below it, it does not
 *  cross zero when the running total never does, and it ends on a round number with room above the tallest bar for its label. */
export function axisRange(bars: Bar[]): Range {
  // A total below zero hangs from zero, so its top is at zero and its label needs the room above that.
  const levels = bars.flatMap((b) => (b.kind === "total" ? (b.end < 0 ? [b.end, 0] : [b.end]) : [b.start, b.end]));
  if (levels.length === 0) return { min: 0, max: 1, step: 1 };
  const low = Math.min(...levels), high = Math.max(...levels);
  const span = high - low || Math.max(Math.abs(high) / 10, 1);
  const rawMin = low - span * 0.2, rawMax = high + span * 0.3;
  const step = niceStep((rawMax - rawMin) / 5);
  const min = Math.floor(rawMin / step) * step;
  return { min: low >= 0 ? Math.max(min, 0) : min, max: Math.ceil(rawMax / step) * step, step };
}

const clamp = (value: number, range: Range) => Math.min(Math.max(value, range.min), range.max);

/** The lowest and highest amount a bar covers on this scale. A total grows from zero, and on a scale that does not hold zero that is kept to
 *  the scale's edge nearest it, so on a zoomed scale a total's bar starts at the bottom of the chart; nothing is drawn outside the scale. */
export function extent(bar: Bar, range: Range): { low: number; high: number } {
  return { low: clamp(Math.min(bar.start, bar.end), range), high: clamp(Math.max(bar.start, bar.end), range) };
}

/** How amounts are written, which the caller knows (the currency and the person's locale): exact for a tooltip, with a sign for a change, and
 *  short for a label that has little room. */
export type Words = { amount: (value: number) => string; change: (value: number) => string; short: (value: number) => string; shortChange: (value: number) => string; whole: (value: number) => string };

/** The room around the plot, shared by the chart and its scale so the two line up: above for a bar's label, below for the names. */
export const GRID = { top: 34, bottom: 58 };

/** The bar's colour: what raises net worth, what lowers it, the app's accent for the totals, and the muted colour for no change. */
const fillOf = (bar: Bar, theme: ChartTheme) => (bar.kind === "total" ? theme.accent : bar.value > 0 ? theme.positive : bar.value < 0 ? theme.negative : theme.muted);

type Api = { coord: (value: number[]) => number[]; size: (value: number[]) => number[] };

/** The ECharts option for the bars. ECharts has no waterfall, so each bar is drawn by a custom series: a rectangle, its label and the thin
 *  dashed connector to the next bar. The scale is not drawn here (see `scaleOption`), so the bars can scroll sideways beside it. */
export function waterfallOption(bars: Bar[], range: Range, theme: ChartTheme, words: Words): EChartsCoreOption {
  return {
    grid: { left: 8, right: 16, top: GRID.top, bottom: GRID.bottom },
    xAxis: {
      type: "category", data: bars.map((b) => b.name), axisTick: { show: false }, axisLine: { lineStyle: { color: theme.border } },
      axisLabel: { interval: 0, width: 92, overflow: "break", color: theme.muted, fontSize: 12, lineHeight: 15 },
    },
    yAxis: { type: "value", min: range.min, max: range.max, interval: range.step, axisLabel: { show: false }, splitLine: { lineStyle: { color: theme.border, opacity: 0.6 } } },
    tooltip: tooltipOption((params) => {
      const bar = bars.find((b) => b.id === (params.data as { id?: string } | undefined)?.id);
      if (!bar) return null;
      return bar.kind === "total"
        ? { title: bar.name, rows: [{ label: "Net worth", value: words.amount(bar.value) }] }
        : { title: bar.name, rows: [{ label: "Change", value: words.change(bar.value) }], note: bar.note };
    }),
    series: [{
      type: "custom", data: bars.map((b, i) => ({ id: b.id, value: [i, b.start, b.end] })),
      renderItem: (params: { dataIndex: number }, api: Api) => {
        const i = params.dataIndex, bar = bars[i];
        const width = api.size([1, 0])[0] * 0.56;
        const x = api.coord([i, 0])[0];
        const { low, high } = extent(bar, range);
        const top = api.coord([i, high])[1];
        const height = Math.max(api.coord([i, low])[1] - top, 2);                 // a step of nothing is still a line
        const children: unknown[] = [
          { type: "rect", shape: { x: x - width / 2, y: top, width, height, r: 2 }, style: { fill: fillOf(bar, theme) } },
          { type: "text", style: { text: bar.kind === "total" ? words.whole(bar.value) : words.shortChange(bar.value), x, y: top - 6, textAlign: "center", textVerticalAlign: "bottom", fill: theme.text, fontSize: 12, fontWeight: 600 } },
        ];
        if (i < bars.length - 1) {                                              // the thin connector from this bar's end to the next bar
          const y = api.coord([i, clamp(bar.end, range)])[1], next = api.coord([i + 1, 0])[0];
          children.push({ type: "line", shape: { x1: x + width / 2, y1: y, x2: next - width / 2, y2: y }, style: { stroke: theme.muted, lineWidth: 1, lineDash: [3, 3], opacity: 0.8 } });
        }
        return { type: "group", children };
      },
    }],
  };
}

/** The scale as a chart of its own, beside the one that scrolls: the same range, top and bottom, and nothing else, so the scale stays in view
 *  while the bars move. */
export function scaleOption(range: Range, theme: ChartTheme, words: Words): EChartsCoreOption {
  return {
    grid: { left: 0, right: 8, top: GRID.top, bottom: GRID.bottom },
    xAxis: { type: "category", data: [""], show: false },
    yAxis: { type: "value", min: range.min, max: range.max, interval: range.step, axisLabel: { color: theme.muted, fontSize: 12, formatter: (value: number) => words.short(value) }, splitLine: { show: false } },
    series: [{ type: "custom", data: [], renderItem: () => ({ type: "group", children: [] }) }],
  };
}

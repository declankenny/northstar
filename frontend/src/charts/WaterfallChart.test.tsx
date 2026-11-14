// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { giveBoxesASize, startCspGuard } from "./chartTesting";
import { echarts } from "./echarts";
import { WaterfallChart } from "./WaterfallChart";
import type { StepNode, Words } from "./waterfall";

let restoreSizes: () => void;
beforeEach(() => {
  restoreSizes = giveBoxesASize(640, 360);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});
afterEach(() => {
  cleanup();
  restoreSizes();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
  document.querySelectorAll(".chart-tooltip").forEach((tip) => tip.remove());
});

const WORDS: Words = {
  amount: (n) => `$${n}`, change: (n) => `${n > 0 ? "+" : ""}$${n}`, short: (n) => `S${n}`, shortChange: (n) => `${n > 0 ? "+" : "-"}S${Math.abs(n)}`, whole: (n) => `W${n}`,
};
const node = (id: string, opening: number, closing: number, note?: string): StepNode => ({ id, name: id.toUpperCase(), value: closing - opening, opening, closing, note });
const NODES = [node("up", 1000, 1600, "2 accounts"), node("down", 500, 300), node("flat", 40, 40)];

const colours = () => {
  const root = document.documentElement;
  root.style.setProperty("--pos", "#118811");
  root.style.setProperty("--neg", "#cc2222");
  root.style.setProperty("--accent", "#2233cc");
  root.style.setProperty("--text", "#101010");
};
const charts = (container: HTMLElement) => Array.from(container.querySelectorAll<HTMLElement>(".chart-canvas"));
const svgOf = (el: HTMLElement) => el.querySelector("svg")!.innerHTML;
const showTip = (container: HTMLElement, dataIndex: number) => {
  const chart = echarts.getInstanceByDom(charts(container)[1])!;
  act(() => { chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex }); });
};

describe("a waterfall", () => {
  it("draws the scale as a chart of its own beside the bars, and keeps the scale out of the way of a screen reader", () => {
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="How it changed" />);
    expect(charts(container)).toHaveLength(2);
    expect(container.querySelector(".bridge-axis")!.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector(".bridge-scroll .chart-canvas")).toBe(charts(container)[1]);
    expect(svgOf(charts(container)[0])).toContain("S");                       // the scale's labels, written by the caller's words
  });

  it("describes the figures to a screen reader, since its marks cannot be reached", () => {
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="How it changed" />);
    expect(charts(container)[1].getAttribute("aria-label")).toBe("How it changed: Opening balance $1540, UP +$600, DOWN $-200, FLAT $0, Closing balance $1940");
  });

  it("colours a step that raises the value green, one that lowers it red, the totals with the accent, and a step of nothing in the muted colour", () => {
    colours();
    document.documentElement.style.setProperty("--muted", "#777777");
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="x" />);
    const svg = svgOf(charts(container)[1]).toLowerCase();
    const fills = Array.from(svg.matchAll(/fill="(#[0-9a-f]{6})"/g)).map((m) => m[1]);
    expect(fills.filter((f) => f === "#2233cc")).toHaveLength(2);              // opening and closing
    expect(fills.filter((f) => f === "#118811")).toHaveLength(1);
    expect(fills.filter((f) => f === "#cc2222")).toHaveLength(1);
    expect(fills.filter((f) => f === "#777777").length).toBeGreaterThanOrEqual(1);
  });

  it("starts at the whole the report gives, not at the sum of the steps", () => {
    const { container } = render(<WaterfallChart nodes={NODES} whole={{ opening: 10_000, closing: 10_400 }} words={WORDS} label="How it changed" />);
    expect(charts(container)[1].getAttribute("aria-label")).toBe("How it changed: Opening balance $10000, UP +$600, DOWN $-200, FLAT $0, Closing balance $10400");
  });

  it("draws a lone rise in green only and a lone fall in red only, so the colour follows the direction", () => {
    colours();
    const fillsOf = (node: StepNode) => {
      const { container, unmount } = render(<WaterfallChart nodes={[node]} words={WORDS} label="x" />);
      const found = Array.from(svgOf(charts(container)[1]).toLowerCase().matchAll(/fill="(#[0-9a-f]{6})"/g)).map((m) => m[1]);
      unmount();
      return found;
    };
    const rise = fillsOf(node("up", 100, 160)), fall = fillsOf(node("down", 160, 100));
    expect(rise).toContain("#118811");
    expect(rise).not.toContain("#cc2222");
    expect(fall).toContain("#cc2222");
    expect(fall).not.toContain("#118811");
  });

  it("joins each bar to the next with a thin dashed line, one fewer than there are bars", () => {
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="x" />);
    expect(svgOf(charts(container)[1]).match(/stroke-dasharray/g)).toHaveLength(NODES.length + 1);          // five bars, four connectors
  });

  it("draws a step of nothing as a thin line, not as nothing", () => {
    colours();
    document.documentElement.style.setProperty("--muted", "#777777");
    const { container } = render(<WaterfallChart nodes={[node("flat", 40, 40)]} words={WORDS} label="x" />);
    const bar = Array.from(svgOf(charts(container)[1]).matchAll(/<path d="([^"]+)" fill="#777777"><\/path>/g)).map((m) => m[1]);
    expect(bar).toHaveLength(1);
    expect(bar[0]).toMatch(/A1 1/);                                            // two pixels thick: its rounded ends have a radius of one
  });

  it("labels each bar with its change (a total with its amount), under the names of the bars", () => {
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="x" />);
    const text = charts(container)[1].textContent!;
    for (const expected of ["W1540", "+S600", "-S200", "W1940", "Opening balance", "Closing balance", "UP", "DOWN", "FLAT"]) expect(text).toContain(expected);
  });

  it("draws a running total that goes below zero and comes back", () => {
    const { container } = render(<WaterfallChart nodes={[node("a", 100, -50), node("b", -400, -300), node("c", 0, 900)]} words={WORDS} label="x" />);
    const text = charts(container)[1].textContent!;
    for (const expected of ["-S150", "+S100", "+S900", "W-300"]) expect(text).toContain(expected);
    expect(container.querySelectorAll(".chart-canvas svg")).toHaveLength(2);
  });

  it("is made wider than its card when there are many steps, so it scrolls and the scale does not", () => {
    const many = Array.from({ length: 12 }, (_, i) => node(`t${i}`, 100, 120 + i));
    const { container } = render(<WaterfallChart nodes={many} words={WORDS} label="x" />);
    const inner = container.querySelector<HTMLElement>(".bridge-scroll > div")!;
    expect(parseInt(inner.style.minWidth, 10)).toBeGreaterThanOrEqual(14 * 100);
    expect(container.querySelector(".bridge-axis")!.querySelector(".bridge-scroll")).toBeNull();
  });

  it("shows a type's change and what it holds when hovered, as markup with no style attribute", () => {
    const guard = startCspGuard();
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="x" />);
    showTip(container, 1);
    const tip = document.querySelector(".chart-tooltip .chart-tip")!;
    expect(tip.textContent).toContain("UP");
    expect(tip.textContent).toContain("+$600");
    expect(tip.textContent).toContain("2 accounts");
    expect(document.querySelector(".chart-tooltip")!.innerHTML).not.toMatch(/\bstyle\s*=/i);
    showTip(container, 0);
    expect(document.querySelector(".chart-tooltip .chart-tip")!.textContent).toContain("Opening balance");
    expect(guard.stop()).toEqual([]);
  });

  it("is drawn again in the new colours when the theme changes, and writes nothing the policy blocks", async () => {
    const guard = startCspGuard();
    colours();
    const { container } = render(<WaterfallChart nodes={NODES} words={WORDS} label="x" />);
    expect(svgOf(charts(container)[1]).toLowerCase()).toContain("#118811");
    act(() => { document.documentElement.style.setProperty("--pos", "#33bb55"); document.documentElement.dataset.theme = "dark"; });
    await waitFor(() => expect(svgOf(charts(container)[1]).toLowerCase()).toContain("#33bb55"));
    expect(svgOf(charts(container)[1]).toLowerCase()).not.toContain("#118811");
    expect(guard.stop()).toEqual([]);
  });
});

// ---- opening and closing types ----

/** Press and release at a point of the chart, the way ECharts is told a click is made (see Chart.test.tsx). */
const clickAt = (container: HTMLElement, x: number, y: number) => {
  const svg = charts(container)[1].querySelector("svg")!;
  for (const type of ["mouseMove", "mouseDown", "mouseUp", "click"] as const) fireEvent[type](svg, { clientX: x, clientY: y });
};
/** Where the text with these words is, from what ECharts wrote: its transform, or its own x and y. */
const textPoint = (container: HTMLElement, words: string): [number, number] => {
  const text = [...charts(container)[1].querySelectorAll("text")].find((t) => t.textContent === words);
  if (!text) throw new Error(`no text ${words}`);
  const moved = /translate\(([\d.-]+) ([\d.-]+)\)/.exec(text.getAttribute("transform") ?? "");
  return moved ? [Number(moved[1]), Number(moved[2]) + 7] : [Number(text.getAttribute("x")), Number(text.getAttribute("y"))];
};
/** The middle of the bar drawn in this colour (the Nth of that colour), from the corners of its path. */
const barPoint = (container: HTMLElement, fill: string, nth = 0): [number, number] => {
  const paths = [...charts(container)[1].querySelectorAll("path")].filter((p) => p.getAttribute("fill")?.toLowerCase() === fill);
  const points = [...(paths[nth].getAttribute("d") ?? "").matchAll(/[ML]([\d.-]+) ([\d.-]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
};

const TYPES: StepNode[] = [
  { id: "t1", name: "Brokerage", value: 600, opening: 1000, closing: 1600, note: "2 accounts", children: [
    { id: "a1", name: "Index fund", value: 700, opening: 1000, closing: 1700, note: "Oct 1 → Oct 31", href: "/accounts/1" },
    { id: "a2", name: "Stocks", value: -100, opening: 0, closing: -100, note: "No balance on Oct 1", href: "/accounts/2" }] },
  { id: "t2", name: "Mortgage", value: -200, opening: 500, closing: 300, note: "1 account", children: [
    { id: "a3", name: "Home loan", value: -200, opening: 500, closing: 300, href: "/accounts/3" }] },
  { id: "t3", name: "Cash", value: 90, opening: 10, closing: 100, note: "no accounts inside" },
];
const rendered = (open: string[] = []) => {
  colours();
  const calls = { toggle: vi.fn(), open: vi.fn() };
  const view = render(<WaterfallChart nodes={TYPES} words={WORDS} label="x" isOpen={(id) => open.includes(id)} onToggle={calls.toggle} onOpen={calls.open} />);
  return { ...view, ...calls };
};

describe("opening and closing types in the chart", () => {
  it("opens a type when its bar is clicked", () => {
    const { container, toggle, open } = rendered();
    clickAt(container, ...barPoint(container, "#118811"));                       // the one type that rose in the Brokerage colour is the first green bar
    expect(toggle).toHaveBeenCalledWith("t1");
    expect(open).not.toHaveBeenCalled();
  });

  it("opens a type when its name under the axis is clicked, and says on the name that it can be opened", () => {
    const { container, toggle } = rendered();
    clickAt(container, ...textPoint(container, "▸ Brokerage"));
    expect(toggle).toHaveBeenCalledWith("t1");
    clickAt(container, ...textPoint(container, "▸ Mortgage"));
    expect(toggle).toHaveBeenLastCalledWith("t2");
  });

  it("does nothing for the name of a step with nothing inside it, which has no sign that it can be opened", () => {
    const { container, toggle, open } = rendered();
    expect([...charts(container)[1].querySelectorAll("text")].some((t) => t.textContent === "Cash")).toBe(true);
    clickAt(container, ...textPoint(container, "Cash"));
    expect(toggle).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });

  it("shows an open type as its accounts, with a bracket under them named for the type", () => {
    const { container } = rendered(["t1"]);
    const text = charts(container)[1].textContent!;
    for (const expected of ["Index fund", "Stocks", "▾ Brokerage", "▸ Mortgage"]) expect(text).toContain(expected);
    expect(text).not.toContain("▸ Brokerage");
    expect(charts(container)[1].getAttribute("aria-label")).toContain("Index fund +$700");
  });

  it("closes an open type when the name on its bracket is clicked", () => {
    const { container, toggle } = rendered(["t1"]);
    clickAt(container, ...textPoint(container, "▾ Brokerage"));
    expect(toggle).toHaveBeenCalledWith("t1");
  });

  it("opens an account when its bar is clicked, and not when its name under the axis is", () => {
    const { container, toggle, open } = rendered(["t2"]);
    clickAt(container, ...textPoint(container, "Home loan"));
    expect(open).not.toHaveBeenCalled();
    clickAt(container, ...barPoint(container, "#cc2222"));
    expect(open).toHaveBeenCalledWith("/accounts/3");
    expect(toggle).not.toHaveBeenCalled();
  });

  it("colours a bracket by what the type itself did, and writes it in that colour", () => {
    const { container } = rendered(["t2"]);                                       // the mortgage fell
    const bracket = [...charts(container)[1].querySelectorAll("text")].find((t) => t.textContent === "▾ Mortgage")!;
    expect(bracket.getAttribute("fill")?.toLowerCase()).toBe("#cc2222");
    cleanup();
    const up = rendered(["t1"]);
    expect([...charts(up.container)[1].querySelectorAll("text")].find((t) => t.textContent === "▾ Brokerage")!.getAttribute("fill")?.toLowerCase()).toBe("#118811");
  });

  it("leaves the scale column the same height as the chart when a bracket needs more room below", () => {
    const shut = rendered();
    const shutBottom = echarts.getInstanceByDom(charts(shut.container)[0])!.getOption().grid as { bottom: number }[];
    cleanup();
    const open = rendered(["t1"]);
    const chart = echarts.getInstanceByDom(charts(open.container)[1])!.getOption().grid as { bottom: number }[];
    const scale = echarts.getInstanceByDom(charts(open.container)[0])!.getOption().grid as { bottom: number }[];
    expect(chart[0].bottom).toBe(scale[0].bottom);
    expect(scale[0].bottom).toBeGreaterThan(shutBottom[0].bottom);
  });
});

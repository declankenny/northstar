// @vitest-environment jsdom
import { act, cleanup, render, waitFor } from "@testing-library/react";
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

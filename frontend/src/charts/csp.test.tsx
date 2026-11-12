// @vitest-environment jsdom
// The app's Content-Security-Policy (`style-src 'self'`) blocks a style attribute written as markup, which is what ECharts' default tooltip
// does. jsdom cannot enforce a policy, so these tests watch the channels a style would arrive by (see chartTesting.ts) while a chart loads,
// is hovered and changes theme, and prove the watcher sees what the default tooltip does. The wrapper is also checked in a real browser.
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Chart } from "./Chart";
import { giveBoxesASize, startCspGuard } from "./chartTesting";
import { echarts } from "./echarts";
import { TreemapDrill } from "./TreemapDrill";
import type { TreeNode } from "./treemap";

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

const TREE: TreeNode = {
  id: "assets", name: "Assets", size: 100, children: [
    { id: "savings", name: "Savings", size: 60, slot: 1, children: [{ id: "alpha", name: "Alpha", size: 60 }] },
    { id: "checking", name: "Checking", size: 40, slot: 2 },
  ],
};
const dollars = (node: TreeNode) => `$${node.size}.00`;
const point = (container: HTMLElement) => container.querySelector("svg")!;
const hoverAt = (container: HTMLElement, x: number, y: number) => fireEvent.mouseMove(point(container), { clientX: x, clientY: y });
/** Hover block number `block` (from 0) the way ECharts is told to. A treemap counts its invisible root as item 0, so a block is one more. */
const showTip = (container: HTMLElement, block: number) => {
  const chart = echarts.getInstanceByDom(container.querySelector(".chart-canvas") as HTMLElement)!;
  act(() => { chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: block + 1 }); });
};

describe("the watcher", () => {
  it("sees a style attribute written as markup or through setAttribute, and a style element, in each way", () => {
    const guard = startCspGuard();
    const host = document.createElement("div");
    document.body.appendChild(host);
    host.innerHTML = '<span style="color: red">x</span>';
    host.insertAdjacentHTML("beforeend", "<b style='x'>y</b>");
    host.setAttribute("style", "color: blue");
    host.outerHTML = '<div style="margin: 0">z</div>';
    document.head.appendChild(document.createElement("style"));
    const found = guard.stop();
    expect(found.map((line) => line.split(":")[0])).toEqual(["innerHTML", "insertAdjacentHTML", "setAttribute", "outerHTML", "<style> element"]);
    document.head.querySelectorAll("style").forEach((el) => el.remove());
    document.body.innerHTML = "";
  });

  it("lets through what the policy allows: markup without a style, and a style set through the element's style property", () => {
    const guard = startCspGuard();
    const host = document.createElement("div");
    host.innerHTML = '<span class="chart-tip">x</span>';
    host.style.color = "red";
    host.style.cssText = "margin: 0";
    host.setAttribute("class", "a");
    expect(guard.stop()).toEqual([]);
  });

  it("puts everything back when it stops", () => {
    startCspGuard().stop();
    const guard = startCspGuard();
    guard.stop();
    const host = document.createElement("div");
    host.innerHTML = '<span style="color: red">x</span>';
    host.setAttribute("style", "color: red");
    expect(host.innerHTML).toContain("style");
    expect(startCspGuard().stop()).toEqual([]);
  });
});

describe("the default ECharts tooltip", () => {
  it("is what the watcher exists for: it writes a style attribute as markup", () => {
    const option = { series: [{ type: "treemap", left: 0, top: 0, right: 0, bottom: 0, breadcrumb: { show: false }, nodeClick: false,
      data: [{ id: "a", name: "A", value: 60 }, { id: "b", name: "B", value: 40 }] }], tooltip: { trigger: "item" } };
    const { container } = render(<Chart option={option} label="Assets" />);
    const guard = startCspGuard();
    showTip(container, 0);
    const found = guard.stop();
    expect(found.length).toBeGreaterThan(0);
    expect(found.some((line) => line.startsWith("innerHTML") && /style\s*=/.test(line))).toBe(true);
  });
});

describe("a chart made with the wrapper", () => {
  it("writes nothing the policy blocks on load, on hover, when drilled into, and when the theme changes", async () => {
    const guard = startCspGuard();
    const { container } = render(<TreemapDrill root={TREE} format={dollars} label="Assets" />);

    hoverAt(container, 100, 100);                                         // the way a person hovers
    showTip(container, 0);                                                // and the way ECharts is told to
    const tip = document.querySelector(".chart-tooltip .chart-tip");
    expect(tip).toBeTruthy();
    expect(tip!.textContent).toContain("Savings");
    expect(tip!.textContent).toContain("$60.00");
    expect(tip!.querySelector(".chart-slot-1")).toBeTruthy();
    expect(document.querySelector(".chart-tooltip")!.innerHTML).not.toMatch(/\bstyle\s*=/i);

    for (const [theme, text] of [["light", "#111111"], ["dark", "#eeeeee"]] as const) {   // the theme changes, as the app does it
      act(() => { document.documentElement.style.setProperty("--text", text); document.documentElement.dataset.theme = theme; });
      await waitFor(() => expect(container.querySelector("svg")).toBeTruthy());
      showTip(container, 1);
      expect(document.querySelector(".chart-tooltip .chart-tip")!.textContent).toContain("Checking");
    }

    fireEvent.click(container.querySelector(".chart-list button")!);        // drill into Savings, and hover what is in it
    showTip(container, 0);
    expect(document.querySelector(".chart-tooltip .chart-tip")!.textContent).toContain("Alpha");

    expect(guard.stop()).toEqual([]);
  });

  it("is dressed by the page's colours again after a theme change: the blocks take the new slot colours", async () => {
    document.documentElement.style.setProperty("--chart-1", "#2a78d6");
    const { container } = render(<TreemapDrill root={TREE} format={dollars} label="Assets" />);
    expect(container.querySelector("svg")!.innerHTML).toContain("#2a78d6");
    act(() => { document.documentElement.style.setProperty("--chart-1", "#3987e5"); document.documentElement.dataset.theme = "dark"; });
    await waitFor(() => expect(container.querySelector("svg")!.innerHTML).toContain("#3987e5"));
    expect(container.querySelector("svg")!.innerHTML).not.toContain("#2a78d6");
  });
});

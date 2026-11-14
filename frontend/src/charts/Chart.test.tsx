// @vitest-environment jsdom
// How chart code is tested. ECharts' SVG renderer mounts in jsdom, so a chart is tested as DOM: render the real component, look at the SVG
// it drew and the markup it wrote, drive hover with ECharts' own actions (`showTip`), and change the theme the way the app does (the
// `data-theme` of the page). jsdom has no layout and no canvas, so `giveBoxesASize` gives every element a size and text is measured by
// ECharts' own fallback. jsdom cannot enforce a Content-Security-Policy: csp.test.tsx watches the channels the policy blocks, and the
// wrapper is also checked once in a real browser under the app's real policy. A chart type is added with a probe like the treemap's below.
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Chart } from "./Chart";
import { giveBoxesASize } from "./chartTesting";
import { echarts, type EChartsCoreOption } from "./echarts";

let restoreSizes: () => void;
beforeEach(() => {
  restoreSizes = giveBoxesASize(640, 360);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);       // jsdom has no canvas; ECharts then estimates text widths
});
afterEach(() => {
  cleanup();
  restoreSizes();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const treemap = (fill = "#2a78d6"): EChartsCoreOption => ({
  series: [{
    type: "treemap", left: 0, top: 0, right: 0, bottom: 0, breadcrumb: { show: false }, nodeClick: false,
    data: [{ id: "s", name: "Savings", value: 60, itemStyle: { color: fill } }, { id: "c", name: "Checking", value: 40, itemStyle: { color: fill } }],
  }],
});
const canvas = (container: HTMLElement) => container.querySelector<HTMLElement>(".chart-canvas")!;
/** A click on the chart at a point: ECharts makes a click of a press and a release in the same place, as a browser's pointer does. */
const clickAt = (container: HTMLElement, x: number, y: number) => {
  const target = container.querySelector("svg")!;
  for (const type of ["mouseMove", "mouseDown", "mouseUp", "click"] as const) fireEvent[type](target, { clientX: x, clientY: y });
};

describe("the chart", () => {
  it("draws the treemap as SVG, a block and a label for each node", () => {
    const { container } = render(<Chart option={treemap()} label="Assets" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toBeTruthy();
    expect(svg.querySelectorAll("path").length).toBeGreaterThanOrEqual(2);
    const text = [...svg.querySelectorAll("text")].map((t) => t.textContent);
    expect(text).toEqual(expect.arrayContaining(["Savings", "Checking"]));
    expect(svg.getAttribute("width")).toBe("640");
    expect(svg.getAttribute("height")).toBe("360");
  });

  it("draws a custom series on a grid as SVG, which is how a waterfall is drawn: its shapes, its text and its axis labels", () => {
    const option: EChartsCoreOption = {
      grid: { left: 0, right: 0, top: 0, bottom: 30 }, xAxis: { type: "category", data: ["One", "Two"] }, yAxis: { type: "value", min: 0, max: 10 },
      series: [{
        type: "custom", data: [{ id: "a", value: [0, 4] }, { id: "b", value: [1, 8] }],
        renderItem: (params: { dataIndex: number }, api: { coord: (v: number[]) => number[]; size: (v: number[]) => number[] }) => {
          const [x, y] = api.coord([params.dataIndex, params.dataIndex === 0 ? 4 : 8]);
          return { type: "group", children: [{ type: "rect", shape: { x: x - 10, y, width: 20, height: 30 }, style: { fill: "#2a78d6" } }, { type: "text", style: { text: `bar${params.dataIndex}`, x, y: y - 4 } }] };
        },
      }],
    };
    const { container } = render(<Chart option={option} label="Bars" />);
    const svg = container.querySelector("svg")!;
    expect(svg.innerHTML).toContain("#2a78d6");
    expect([...svg.querySelectorAll("text")].map((t) => t.textContent)).toEqual(expect.arrayContaining(["bar0", "bar1", "One", "Two"]));
  });

  it("is an image to a screen reader, described by its label", () => {
    const { container } = render(<Chart option={treemap()} label="Assets, by account type" />);
    const box = canvas(container);
    expect(box.getAttribute("role")).toBe("img");
    expect(box.getAttribute("aria-label")).toBe("Assets, by account type");
  });

  it("draws again when its option changes, and a new colour replaces the old", () => {
    const { container, rerender } = render(<Chart option={treemap("#2a78d6")} label="Assets" />);
    expect(container.innerHTML).toContain("#2a78d6");
    rerender(<Chart option={treemap("#eb6834")} label="Assets" />);
    expect(container.innerHTML).toContain("#eb6834");
    expect(container.innerHTML).not.toContain("#2a78d6");
  });

  it("follows its container when that changes size", () => {
    let notify: () => void = () => {};
    vi.stubGlobal("ResizeObserver", class { constructor(callback: () => void) { notify = callback; } observe() {} disconnect() {} });
    const { container } = render(<Chart option={treemap()} label="Assets" />);
    expect(container.querySelector("svg")!.getAttribute("width")).toBe("640");
    restoreSizes();
    restoreSizes = giveBoxesASize(300, 200);
    notify();
    expect(container.querySelector("svg")!.getAttribute("width")).toBe("300");
    expect(container.querySelector("svg")!.getAttribute("height")).toBe("200");
  });

  it("works without ResizeObserver, which not every environment has", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    expect(() => render(<Chart option={treemap()} label="Assets" />)).not.toThrow();
  });

  it("is disposed with the component, and watches nothing after it", () => {
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect = disconnect; });
    const { container, unmount } = render(<Chart option={treemap()} label="Assets" />);
    const box = canvas(container);
    expect(echarts.getInstanceByDom(box)).toBeTruthy();
    unmount();
    expect(echarts.getInstanceByDom(box)).toBeFalsy();
    expect(disconnect).toHaveBeenCalled();
  });

  it("tells its owner which mark was clicked and what data it holds", () => {
    const onClick = vi.fn();
    const { container } = render(<Chart option={treemap()} label="Assets" onClick={onClick} />);
    // The mark under the pointer is found by position: the first block is the left 60%.
    clickAt(container, 100, 100);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick.mock.calls[0][0]).toMatchObject({ name: "Savings", data: { id: "s" } });
  });

  it("tells its owner which axis label was clicked, when the chart asks for them, and says so apart from a mark", () => {
    const option: EChartsCoreOption = {
      grid: { left: 0, right: 0, top: 0, bottom: 40 }, xAxis: { type: "category", data: ["a", "b"], triggerEvent: true, axisLabel: { formatter: (id: string) => `Name ${id}` } },
      yAxis: { type: "value", min: 0, max: 10 }, series: [{ type: "custom", data: [], renderItem: () => ({ type: "group", children: [] }) }],
    };
    const onClick = vi.fn();
    const { container } = render(<Chart option={option} label="Bars" onClick={onClick} />);
    const label = [...container.querySelectorAll("svg text")].find((t) => t.textContent === "Name b")!;
    const moved = /translate\(([\d.-]+) ([\d.-]+)\)/.exec(label.getAttribute("transform") ?? "")!;
    clickAt(container, Number(moved[1]), Number(moved[2]) + 7);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick.mock.calls[0][0]).toMatchObject({ axis: "b" });
  });

  it("does not say a click on a mark was on an axis", () => {
    const onClick = vi.fn();
    const { container } = render(<Chart option={treemap()} label="Assets" onClick={onClick} />);
    clickAt(container, 100, 100);
    expect(onClick.mock.calls[0][0].axis).toBeUndefined();
  });

  it("uses the latest click handler without drawing again", () => {
    const first = vi.fn(), second = vi.fn(), option = treemap();
    const { container, rerender } = render(<Chart option={option} label="Assets" onClick={first} />);
    const svgBefore = container.querySelector("svg");
    rerender(<Chart option={option} label="Assets" onClick={second} />);
    clickAt(container, 100, 100);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    expect(container.querySelector("svg")).toBe(svgBefore);
  });

  it("replaces the marks when the data changes, so none of the old ones are left behind", () => {
    const named = (...names: string[]): EChartsCoreOption => ({
      series: [{ type: "treemap", left: 0, top: 0, right: 0, bottom: 0, breadcrumb: { show: false }, nodeClick: false, data: names.map((name, i) => ({ id: name, name, value: 10 + i })) }],
    });
    const { container, rerender } = render(<Chart option={named("A", "B")} label="Assets" />);
    const texts = () => [...container.querySelectorAll("svg text")].map((t) => t.textContent).sort();
    expect(texts()).toEqual(["A", "B"]);
    rerender(<Chart option={named("C", "D", "E")} label="Assets" />);
    expect(texts()).toEqual(["C", "D", "E"]);
    expect(container.querySelectorAll("svg").length).toBe(1);
  });
});

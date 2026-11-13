// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { giveBoxesASize } from "./chartTesting";
import { TreemapDrill } from "./TreemapDrill";
import { slotOf, tooLittleRoom, type TreeNode, trailOf, treemapOption } from "./treemap";
import { readChartTheme } from "./theme";

let restoreSizes: () => void;
beforeEach(() => {
  restoreSizes = giveBoxesASize(640, 360);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});
afterEach(() => {
  cleanup();
  restoreSizes();
  vi.restoreAllMocks();
});

const money = (cents: number) => `$${(cents / 100).toFixed(2)}`;
const format = (node: TreeNode) => money(node.size);

// Synthetic: a type holds accounts, and a type may have nothing in it (a leaf).
const TREE = (): TreeNode => ({
  id: "assets", name: "Assets", size: 100_00, children: [
    { id: "savings", name: "Savings", size: 60_00, slot: 1, children: [{ id: "alpha", name: "Alpha", size: 40_00 }, { id: "beta", name: "Beta", size: 20_00 }] },
    { id: "checking", name: "Checking", size: 30_00, slot: 2, children: [{ id: "gamma", name: "Gamma", size: 30_00 }] },
    { id: "cash", name: "Cash", size: 10_00, slot: 3 },
  ],
});
const list = () => within(screen.getByRole("list", { name: "Assets, as a list" }));
const crumbs = () => screen.getByRole("navigation", { name: "Where you are in Assets" });
const labels = (container: HTMLElement) => [...container.querySelectorAll("svg text")].map((t) => t.textContent);
const show = (props: Partial<Parameters<typeof TreemapDrill>[0]> = {}) => render(<TreemapDrill root={TREE()} format={format} label="Assets" {...props} />);

describe("the nodes and slots", () => {
  it("follows a path of ids from the root and stops at the first one that is not there", () => {
    const root = TREE();
    expect(trailOf(root, []).map((n) => n.id)).toEqual(["assets"]);
    expect(trailOf(root, ["savings", "alpha"]).map((n) => n.id)).toEqual(["assets", "savings", "alpha"]);
    expect(trailOf(root, ["savings", "nope", "alpha"]).map((n) => n.id)).toEqual(["assets", "savings"]);
    expect(trailOf(root, ["nope"]).map((n) => n.id)).toEqual(["assets"]);
  });

  it("gives a block its own slot, else its parent's, else none, and never one that is not a slot", () => {
    const root = TREE();
    const savings = root.children![0];
    expect(slotOf(savings, [root])).toBe(1);
    expect(slotOf(savings.children![0], [root, savings])).toBe(1);
    expect(slotOf(root, [root])).toBeUndefined();
    expect(slotOf({ id: "x", name: "X", size: 1, slot: 0 }, [root])).toBeUndefined();
    expect(slotOf({ id: "x", name: "X", size: 1, slot: -3 }, [root])).toBeUndefined();
    expect(slotOf({ id: "x", name: "X", size: 1, slot: 1.5 }, [root])).toBeUndefined();
  });

  it("reuses the colours in order when there are more entities than colours, and does not group the surplus: that is not the palette's decision", () => {
    const root: TreeNode = { id: "r", name: "Root", size: 1, children: Array.from({ length: 20 }, (_, i) => ({ id: `t${i + 1}`, name: `Type ${i + 1}`, size: 1, slot: i + 1 })) };
    expect([1, 8, 9, 16, 17, 20].map((n) => slotOf(root.children![n - 1], [root]))).toEqual([1, 8, 9, 16, 1, 4]);
    const { container } = render(<TreemapDrill root={root} format={format} label="Assets" />);
    const buttons = list().getAllByRole("button");
    expect(buttons).toHaveLength(20);                                          // every type is its own entry: running out of colours folds nothing
    expect(buttons.map((b) => b.textContent)).not.toContain("Other");
    const classes = [...container.querySelectorAll(".chart-list .chart-swatch")].map((s) => [...s.classList].find((c) => c.startsWith("chart-slot")));
    expect(classes.slice(14)).toEqual(["chart-slot-15", "chart-slot-16", "chart-slot-1", "chart-slot-2", "chart-slot-3", "chart-slot-4"]);
  });

  it("colours a block by its entity's slot and labels it for a reader of the colour behind it", () => {
    const theme = { ...readChartTheme(), series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"], muted: "#898781" };
    const root = TREE();
    const option = treemapOption(root.children!, [root], theme, format) as { series: { data: { id: string; itemStyle: { color: string }; label: { color: string } }[] }[] };
    const [savings, checking, cash] = option.series[0].data;
    expect([savings.itemStyle.color, checking.itemStyle.color, cash.itemStyle.color]).toEqual(["#2a78d6", "#eb6834", "#1baf7a"]);
    expect(savings.label.color).toBe("#ffffff");
    const yellow = treemapOption([{ id: "y", name: "Y", size: 1, slot: 4 }], [root], theme, format) as typeof option;
    expect(yellow.series[0].data[0].label.color).toBe("#0b0b0b");
    const none = treemapOption([{ id: "n", name: "N", size: 1 }], [root], theme, format) as typeof option;
    expect(none.series[0].data[0].itemStyle.color).toBe("#898781");
  });
});

describe("what is drawn, what is only listed, and what is labelled", () => {
  // A type with three accounts: one that fills most of the chart, a tiny one, an overdrawn one and one with no balance (no area).
  const MIXED = (): TreeNode => ({
    id: "assets", name: "Assets", size: 1_001, children: [
      { id: "big", name: "Big", size: 1_000, slot: 1, note: "Balance 1 Mar" },
      { id: "tiny", name: "Tiny", size: 1, slot: 1, note: "Balance 2 Mar" },
      { id: "over", name: "Overdrawn", size: 0, slot: 1, note: "Balance 3 Mar" },
      { id: "none", name: "Empty", size: 0, slot: 1, note: "No balance" },
    ],
  });
  const theme = readChartTheme();
  type Opt = { series: { data: { id: string; label: { show: boolean } }[] }[]; tooltip: { formatter: (p: unknown) => string } };

  it("draws only the nodes that have an area, and lists every node, marking the ones that are not drawn", () => {
    const root = MIXED();
    const option = treemapOption(root.children!, [root], theme, format) as unknown as Opt;
    expect(option.series[0].data.map((d) => d.id)).toEqual(["big", "tiny"]);
    render(<TreemapDrill root={root} format={format} label="Assets" />);
    expect(list().getAllByRole("button").map((b) => b.textContent)).toEqual(
      ["Big$10.00", "Tiny$0.01", "Overdrawn · not in the chart$0.00", "Empty · not in the chart$0.00"]);
  });

  it("has no chart at all when nothing in the node can be drawn, and still lists everything", () => {
    const root: TreeNode = { id: "r", name: "Assets", size: 0, children: [{ id: "a", name: "A", size: 0 }, { id: "b", name: "B", size: 0 }] };
    const { container } = render(<TreemapDrill root={root} format={format} label="Assets" />);
    expect(container.querySelector(".chart-canvas")).toBeNull();
    expect(list().getAllByRole("button")).toHaveLength(2);
  });

  it("gives a label only to a block with room for it: the small one is named by the list and the tooltip", () => {
    const { container } = render(<TreemapDrill root={MIXED()} format={format} label="Assets" />);
    expect(labels(container)).toEqual(expect.arrayContaining(["Big", "$10.00"]));
    expect(labels(container)).not.toContain("Tiny");
    expect(list().getByRole("button", { name: /Tiny/ })).toBeTruthy();
  });

  it("finds the blocks with too little room from the layout: under 78 wide or 50 high, and not a block that has none", () => {
    const layouts = [{ width: 640, height: 360 }, { width: 200, height: 100 }, { width: 77, height: 100 }, { width: 200, height: 49 }, { width: 78, height: 50 }, undefined];
    const chart = { getModel: () => ({ getSeriesByIndex: () => ({ getData: () => ({ getItemLayout: (i: number) => layouts[i] }) }) }) };
    const nodes = ["roomy", "narrow", "short", "just enough", "unplaced"].map((id) => ({ id, name: id, size: 1 }));
    expect(tooLittleRoom(chart, nodes)).toEqual(["narrow", "short"]);              // the first layout item is the root, so the nodes start at 1
  });

  it("lets a label be hidden by the ids it is given, and shows the others", () => {
    const root = MIXED();
    const option = treemapOption(root.children!, [root], theme, format, new Set(["tiny"])) as unknown as Opt;
    expect(option.series[0].data.map((d) => [d.id, d.label.show])).toEqual([["big", true], ["tiny", false]]);
  });

  it("puts the colour square in the tooltip's title row, with the value and the node's own note, and no square on the rows", () => {
    const root = MIXED();
    const option = treemapOption(root.children!, [root], theme, format) as unknown as Opt;
    const html = option.tooltip.formatter({ name: "Big", data: option.series[0].data[0] });
    expect(html).toContain('<div class="chart-tip-title"><span class="chart-swatch chart-slot-1"></span><span>Big</span></div>');
    expect(html).toContain("$10.00");
    expect(html).toContain("Balance 1 Mar");
    expect(html.match(/chart-swatch/g)).toHaveLength(1);
  });
});

describe("a treemap you can drill into", () => {
  it("starts at the top: the breadcrumb is the root, the chart and the list show what is directly in it", () => {
    const { container } = show();
    expect(within(crumbs()).getByText("Assets").getAttribute("aria-current")).toBe("location");
    expect(within(crumbs()).queryByRole("button")).toBeNull();
    expect(list().getAllByRole("button").map((b) => b.textContent)).toEqual(["Savings ▸$60.00", "Checking ▸$30.00", "Cash$10.00"]);
    expect(labels(container)).toEqual(expect.arrayContaining(["Savings", "$60.00", "Checking", "Cash"]));
    expect(container.querySelector(".chart-canvas")!.getAttribute("aria-label")).toBe("Assets: Assets");
  });

  it("drills into a node from its button, shows what is in it, and keeps its colour", () => {
    const { container } = show();
    fireEvent.click(list().getByRole("button", { name: /Savings/ }));
    expect(crumbs().textContent).toBe("Assets › Savings");
    expect(list().getAllByRole("button").map((b) => b.textContent)).toEqual(["Alpha$40.00", "Beta$20.00"]);
    expect(labels(container)).toEqual(expect.arrayContaining(["Alpha", "Beta"]));
    expect(labels(container)).not.toContain("Checking");
    for (const swatch of container.querySelectorAll(".chart-list .chart-swatch")) expect(swatch.classList.contains("chart-slot-1")).toBe(true);
    expect(container.querySelector(".chart-canvas")!.getAttribute("aria-label")).toBe("Assets: Savings");
  });

  it("drills into a node by clicking its block in the chart", () => {
    const { container } = show();
    const svg = container.querySelector("svg")!;
    for (const type of ["mouseMove", "mouseDown", "mouseUp", "click"] as const) fireEvent[type](svg, { clientX: 100, clientY: 100 });    // the first block: Savings
    expect(crumbs().textContent).toBe("Assets › Savings");
  });

  it("goes back up from the breadcrumb, to any level", () => {
    const deep: TreeNode = { id: "r", name: "Root", size: 1, children: [{ id: "a", name: "A", size: 1, children: [{ id: "b", name: "B", size: 1, children: [{ id: "c", name: "C", size: 1 }] }] }] };
    render(<TreemapDrill root={deep} format={format} label="Assets" />);
    fireEvent.click(screen.getByRole("button", { name: /^A/ }));
    fireEvent.click(screen.getByRole("button", { name: /^B/ }));
    expect(crumbs().textContent).toBe("Root › A › B");
    fireEvent.click(within(crumbs()).getByRole("button", { name: "A" }));
    expect(crumbs().textContent).toBe("Root › A");
    fireEvent.click(within(crumbs()).getByRole("button", { name: "Root" }));
    expect(crumbs().textContent).toBe("Root");
  });

  it("calls for the record behind a node that has nothing in it, and stays where it is", () => {
    const onLeaf = vi.fn();
    show({ onLeaf });
    fireEvent.click(list().getByRole("button", { name: /Cash/ }));
    expect(onLeaf).toHaveBeenCalledTimes(1);
    expect(onLeaf.mock.calls[0][0]).toMatchObject({ id: "cash" });
    expect(crumbs().textContent).toBe("Assets");
    fireEvent.click(list().getByRole("button", { name: /Savings/ }));
    fireEvent.click(list().getByRole("button", { name: /Alpha/ }));
    expect(onLeaf).toHaveBeenCalledTimes(2);
    expect(crumbs().textContent).toBe("Assets › Savings");
  });

  it("does everything the chart does with a keyboard: every control is a real button in the tab order, and says what it opens", () => {
    show();
    const buttons = list().getAllByRole("button");
    for (const button of buttons) {
      expect(button.tagName).toBe("BUTTON");
      expect((button as HTMLButtonElement).disabled).toBe(false);
      expect(button.tabIndex).toBeGreaterThanOrEqual(0);
    }
    expect(buttons[0].textContent).toContain("▸");                       // a node with something in it says so
    expect(buttons[2].textContent).not.toContain("▸");
    buttons[0].focus();
    expect(document.activeElement).toBe(buttons[0]);
    expect(screen.getByRole("list", { name: "Assets, as a list" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Where you are in Assets" })).toBeTruthy();
  });

  it("moves focus to where you now are after drilling in or going back, because the button that had it is gone", () => {
    const deep: TreeNode = { id: "r", name: "Root", size: 1, children: [{ id: "a", name: "A", size: 1, children: [{ id: "b", name: "B", size: 1, children: [{ id: "c", name: "C", size: 1 }] }] }] };
    render(<TreemapDrill root={deep} format={format} label="Assets" />);
    const current = () => within(crumbs()).getByText((_, el) => el?.getAttribute("aria-current") === "location");
    const first = screen.getByRole("button", { name: /^A/ });
    first.focus();
    fireEvent.click(first);                                                        // drill into A from its button
    expect(document.activeElement).toBe(current());
    expect(document.activeElement!.textContent).toBe("A");
    const second = screen.getByRole("button", { name: /^B/ });
    second.focus();
    fireEvent.click(second);
    expect(document.activeElement!.textContent).toBe("B");
    const back = within(crumbs()).getByRole("button", { name: "Root" });
    back.focus();
    fireEvent.click(back);                                                         // and back up from the breadcrumb, whose button became text
    expect(document.activeElement).toBe(current());
    expect(document.activeElement!.textContent).toBe("Root");
    expect(document.activeElement).not.toBe(document.body);
    // The place is not in the tab order by itself, only a target for focus, and what is inside it comes next.
    expect(current().tabIndex).toBe(-1);
  });

  it("leaves focus on a node with nothing inside it, which does not go anywhere, and does not take it for a click on the chart", () => {
    const onLeaf = vi.fn();
    const { container } = show({ onLeaf });
    const leaf = list().getByRole("button", { name: /Cash/ });
    leaf.focus();
    fireEvent.click(leaf);
    expect(onLeaf).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(leaf);
    (document.activeElement as HTMLElement).blur();
    const svg = container.querySelector("svg")!;
    for (const type of ["mouseMove", "mouseDown", "mouseUp", "click"] as const) fireEvent[type](svg, { clientX: 100, clientY: 100 });
    expect(crumbs().textContent).toBe("Assets › Savings");                          // it drilled, as a click on the chart does
    expect(document.activeElement).toBe(document.body);                            // and left focus alone
  });

  it("keeps a colour with its entity when another is filtered out, and never gives it to the next one", () => {
    const { container, rerender } = show();
    const slots = () => [...container.querySelectorAll(".chart-list .chart-swatch")].map((s) => [...s.classList].find((c) => c.startsWith("chart-slot")));
    expect(slots()).toEqual(["chart-slot-1", "chart-slot-2", "chart-slot-3"]);
    const without = TREE();
    without.children = without.children!.filter((n) => n.id !== "checking");
    rerender(<TreemapDrill root={without} format={format} label="Assets" />);
    expect(slots()).toEqual(["chart-slot-1", "chart-slot-3"]);
  });

  it("falls back to the nearest place that still exists when what you were looking at is filtered out", () => {
    const { rerender } = show();
    fireEvent.click(list().getByRole("button", { name: /Savings/ }));
    expect(crumbs().textContent).toBe("Assets › Savings");
    const without = TREE();
    without.children = without.children!.filter((n) => n.id !== "savings");
    rerender(<TreemapDrill root={without} format={format} label="Assets" />);
    expect(crumbs().textContent).toBe("Assets");
    expect(list().getAllByRole("button").map((b) => b.textContent)).toEqual(["Checking ▸$30.00", "Cash$10.00"]);
  });

  it("shows a node with no slot in the muted colour, with no slot class on its swatch", () => {
    const root: TreeNode = { id: "r", name: "Root", size: 1, children: [{ id: "n", name: "Nameless", size: 1 }] };
    const { container } = render(<TreemapDrill root={root} format={format} label="Assets" />);
    expect(container.querySelector(".chart-list .chart-swatch")!.className).toBe("chart-swatch");
  });
});

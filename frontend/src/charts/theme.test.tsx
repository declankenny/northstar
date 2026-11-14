// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { contrast, onColor, readChartTheme, SLOTS, useChartTheme } from "./theme";

// The stylesheet as written: vitest does not process CSS, and this test is about what the file says.
const { readFileSync } = (await import("node:fs" as string)) as { readFileSync: (path: string, encoding: string) => string };
const styles = readFileSync("src/styles.css", "utf-8");      // the tests run from the frontend folder

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

const root = () => document.documentElement;
const paint = (colors: Record<string, string>) => Object.entries(colors).forEach(([name, value]) => root().style.setProperty(name, value));

/** The `--chart-n` colours the stylesheet gives one theme. */
function palette(theme: "dark" | "light") {
  const block = styles.match(new RegExp(`:root\\[data-theme="${theme}"\\] \\{([^}]*)\\}`))![1];
  return Array.from({ length: SLOTS }, (_, i) => block.match(new RegExp(`--chart-${i + 1}:\\s*(#[0-9a-f]{6});`, "i"))?.[1]);
}

describe("the colours of a chart", () => {
  it("are read from the page's CSS variables, the text and surface colours and the sixteen categorical slots in order", () => {
    paint({ "--text": "#111111", "--muted": "#222222", "--surface": "#333333", "--border": "#444444", "--chart-1": "#aa0000", "--chart-8": "#00aa00" });
    const theme = readChartTheme();
    expect(theme).toMatchObject({ text: "#111111", muted: "#222222", surface: "#333333", border: "#444444" });
    expect(theme.series).toHaveLength(SLOTS);
    expect(theme.series[0]).toBe("#aa0000");
    expect(theme.series[7]).toBe("#00aa00");
  });

  it("include what raises a value, what lowers it and the accent, from the page's own variables", () => {
    paint({ "--pos": "#118811", "--neg": "#cc2222", "--accent": "#2233cc" });
    expect(readChartTheme()).toMatchObject({ positive: "#118811", negative: "#cc2222", accent: "#2233cc" });
  });

  it("fall back to a visible grey for a variable the page does not have, never to nothing", () => {
    const theme = readChartTheme();
    expect([theme.text, theme.surface, theme.positive, theme.negative, theme.accent, ...theme.series].every((c) => /^#[0-9a-f]{6}$/i.test(c))).toBe(true);
  });

  it("are read again when the page's theme changes", async () => {
    function Probe() {
      return <span data-testid="text">{useChartTheme().text}</span>;
    }
    paint({ "--text": "#111111" });
    render(<Probe />);
    expect(screen.getByTestId("text").textContent).toBe("#111111");
    act(() => { paint({ "--text": "#eeeeee" }); root().dataset.theme = "dark"; });
    await waitFor(() => expect(screen.getByTestId("text").textContent).toBe("#eeeeee"));
    act(() => { paint({ "--text": "#222222" }); root().dataset.theme = "light"; });
    await waitFor(() => expect(screen.getByTestId("text").textContent).toBe("#222222"));
  });

  it("stop being watched when the chart goes away", () => {
    function Probe() {
      return <span>{useChartTheme().text}</span>;
    }
    const { unmount } = render(<Probe />);
    unmount();
    expect(() => { root().dataset.theme = "light"; }).not.toThrow();
  });
});

describe("the label on a block", () => {
  it("is white or near-black, whichever reads better on the fill", () => {
    expect(onColor("#000000")).toBe("#ffffff");
    expect(onColor("#ffffff")).toBe("#0b0b0b");
    expect(onColor("#eda100")).toBe("#0b0b0b");                           // yellow takes dark text
    expect(onColor("#6250d6")).toBe("#ffffff");                           // violet takes white
    expect(onColor("#2a78d6")).toBe("#ffffff");                           // so does blue, where near-black is no better to speak of
    expect(onColor("#1baf7a")).toBe("#0b0b0b");                           // aqua is too light for white
    expect(onColor("not a colour")).toBe("#ffffff");
  });

  it("is never worse than 3:1 on any of the sixteen slots of either theme, which is the least a large label may have", () => {
    for (const theme of ["light", "dark"] as const) {
      for (const fill of palette(theme)) expect(contrast(fill!, onColor(fill!)), `${theme} ${fill}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("measures contrast between 1 and 21", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 0);
    expect(contrast("#777777", "#777777")).toBeCloseTo(1, 5);
  });
});

describe("the palette in the stylesheet", () => {
  // Palette D, extended to sixteen, validated (dataviz validate_palette, neighbouring slots) against each theme's own surface: light on #ffffff,
  // dark on #1a1e23. The lightness band, colour floor, colour-blind and normal-vision separation checks all pass on both; the only warning is
  // that some of the lighter colours are under 3:1 against the surface, which is why every chart has direct labels and a list of its data.
  // Slots 1 to 8 are the chosen hues and 9 to 16 the same hues again, further from their twins.
  const LIGHT = ["#2769b7", "#ad4d18", "#04896a", "#a77e01", "#b14c79", "#197326", "#5c49a3", "#ab413e", "#6daeff", "#f89161", "#5ec8a6", "#d5ab47", "#f589b6", "#63b768", "#9b8bec", "#f7857e"];
  const DARK = ["#417dc7", "#bd6337", "#009c79", "#b58a14", "#c06089", "#3b8841", "#7161b7", "#bd5953", "#225fa6", "#9c4515", "#007a5e", "#926d01", "#9f426c", "#5ba85f", "#9384dd", "#9c3b37"];

  it("has the sixteen validated slots, in order, for each theme", () => {
    expect(palette("light")).toEqual(LIGHT);
    expect(palette("dark")).toEqual(DARK);
  });

  it("has a class for every slot and none past them, and the tooltip and swatches use classes only", () => {
    expect(SLOTS).toBe(16);
    expect(styles).not.toContain(".chart-slot-17 ");
    expect(styles).not.toContain("--chart-17:");
    for (let slot = 1; slot <= SLOTS; slot++) expect(styles).toContain(`.chart-slot-${slot} { background: var(--chart-${slot}); }`);
    expect(styles).toMatch(/\.chart-tip \{/);
  });
});

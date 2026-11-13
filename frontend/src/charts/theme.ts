import { useEffect, useState } from "react";

/** What a chart needs from the app's look. ECharts takes its colours in JavaScript, so they are read from the CSS variables (`--text`,
 *  `--chart-1` ... `--chart-16` in styles.css) and read again when the theme changes. */
export type ChartTheme = {
  text: string; muted: string; surface: string; border: string;
  series: string[];                              // the categorical slots, in their fixed order
};

/** How many colours the palette has. It is a size and never a limit: past it the colours repeat (see `slotFor`). */
export const SLOTS = 16;
const FALLBACK = { text: "#888888", muted: "#888888", surface: "#ffffff", border: "#cccccc", series: "#888888" };

export function readChartTheme(root: HTMLElement = document.documentElement): ChartTheme {
  const style = getComputedStyle(root);
  const variable = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    text: variable("--text", FALLBACK.text), muted: variable("--muted", FALLBACK.muted),
    surface: variable("--surface", FALLBACK.surface), border: variable("--border", FALLBACK.border),
    series: Array.from({ length: SLOTS }, (_, i) => variable(`--chart-${i + 1}`, FALLBACK.series)),
  };
}

/** The theme now, kept current: it is read again when the page's theme changes (the `data-theme` the app sets on the page). */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState(() => readChartTheme());
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setTheme(readChartTheme(root)));
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    setTheme(readChartTheme(root));               // the theme may have changed between the first render and now
    return () => observer.disconnect();
  }, []);
  return theme;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const channel = parseInt(hex.slice(at, at + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast of two `#rrggbb` colours, 1 to 21. */
export function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/** The text colour for a label drawn on a fill: white, unless near-black reads clearly better (by a fifth or more), so no label depends
 *  on the palette being what it was when the label colours were chosen. A fill that is not `#rrggbb` gets white. */
export function onColor(fill: string): string {
  if (!/^#[0-9a-f]{6}$/i.test(fill)) return "#ffffff";
  return contrast(fill, "#ffffff") * 1.2 >= contrast(fill, "#0b0b0b") ? "#ffffff" : "#0b0b0b";
}

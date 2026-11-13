import { SLOTS } from "./theme";

/** A chart's tooltip, as HTML with class names only. The app's Content-Security-Policy (`style-src 'self'`) blocks a `style` attribute in
 *  markup, which is what ECharts' default tooltip writes, so every chart uses this: what is coloured or laid out is done by the classes in
 *  styles.css, and a colour is a slot (`chart-slot-3`) and never a value. Text is escaped. */
export type TipRow = { label: string; value: string; slot?: number };
/** `slot` colours a square in the title row, beside the name: what a hovered mark is. A row's own `slot` is for a chart whose rows are marks. */
export type Tip = { title: string; rows: TipRow[]; note?: string; slot?: number };

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (c) => ESCAPES[c]);

const swatchOf = (slot: number | undefined) => (slot && slot >= 1 && slot <= SLOTS ? `<span class="chart-swatch chart-slot-${Math.trunc(slot)}"></span>` : "");

export function tooltipHtml({ title, rows, note, slot }: Tip): string {
  const lines = rows.map((row) => `<div class="chart-tip-row">${swatchOf(row.slot)}<span class="chart-tip-label">${escapeHtml(row.label)}</span><b class="chart-tip-value">${escapeHtml(row.value)}</b></div>`);
  return `<div class="chart-tip"><div class="chart-tip-title">${swatchOf(slot)}<span>${escapeHtml(title)}</span></div>${lines.join("")}${note ? `<div class="chart-tip-note">${escapeHtml(note)}</div>` : ""}</div>`;
}

/** The `tooltip` option every chart uses: item hover, the class-only content, kept inside the chart, and no frame of its own (the
 *  `chart-tooltip` class in styles.css draws it from the app's colours). `content` says what to show for what ECharts hovered, or null. */
export function tooltipOption(content: (params: { data?: unknown; name?: string }) => Tip | null) {
  return {
    show: true, trigger: "item" as const, confine: true, className: "chart-tooltip",
    backgroundColor: "transparent", borderWidth: 0, padding: 0,
    formatter: (params: { data?: unknown; name?: string }) => {
      const tip = content(params);
      return tip ? tooltipHtml(tip) : "";
    },
  };
}

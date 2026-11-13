import { describe, expect, it } from "vitest";
import { escapeHtml, tooltipHtml, tooltipOption } from "./tooltip";

describe("a chart's tooltip", () => {
  it("is markup with class names only: no style attribute, which the app's policy blocks", () => {
    const html = tooltipHtml({ title: "Savings", rows: [{ label: "Value", value: "$1,200.00", slot: 3 }, { label: "Share", value: "40%" }], note: "Two accounts" });
    expect(html).not.toMatch(/\bstyle\s*=/i);
    expect(html).toContain('class="chart-tip"');
    expect(html).toContain('<span class="chart-swatch chart-slot-3"></span>');
    expect(html).toContain("Savings");
    expect(html).toContain("$1,200.00");
    expect(html).toContain("Two accounts");
  });

  it("colours a swatch by slot, never by a value, and only for a slot there is", () => {
    for (const slot of [0, 17, -1, 3.7 + 14, 100]) expect(tooltipHtml({ title: "t", rows: [{ label: "l", value: "v", slot }] })).not.toContain("chart-swatch");
    for (const slot of [8, 9, 16]) expect(tooltipHtml({ title: "t", rows: [{ label: "l", value: "v", slot }] })).toContain(`chart-slot-${slot}`);
    expect(tooltipHtml({ title: "t", rows: [{ label: "l", value: "v", slot: 2.9 }] })).toContain("chart-slot-2");
    expect(tooltipHtml({ title: "t", rows: [{ label: "l", value: "v", slot: Number.NaN }] })).not.toContain("chart-swatch");
  });

  it("escapes the text it shows, so an account called <img onerror=...> is only text", () => {
    const html = tooltipHtml({ title: '<img src=x onerror="alert(1)">', rows: [{ label: "A & B", value: "'quoted'" }], note: "<b>bold</b>" });
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<b>bold");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    expect(html).toContain("A &amp; B");
    expect(html).toContain("&#39;quoted&#39;");
    expect(escapeHtml(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
  });

  it("is the option every chart uses: hover on an item, kept inside the chart, with no frame of its own", () => {
    const option = tooltipOption((params) => (params.name === "none" ? null : { title: params.name ?? "", rows: [] }));
    expect(option).toMatchObject({ show: true, trigger: "item", confine: true, className: "chart-tooltip", backgroundColor: "transparent", borderWidth: 0, padding: 0 });
    expect(option.formatter({ name: "Savings" })).toBe(tooltipHtml({ title: "Savings", rows: [] }));
    expect(option.formatter({ name: "none" })).toBe("");
  });
});

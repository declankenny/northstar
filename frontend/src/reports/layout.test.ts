import { describe, expect, it } from "vitest";

// The stylesheet as written: vitest does not process CSS, and this is about what the file promises. The tests run from the frontend folder.
const { readFileSync } = (await import("node:fs" as string)) as { readFileSync: (path: string, encoding: string) => string };
const styles = readFileSync("src/styles.css", "utf-8");

describe("the grid a report's sections are laid out on", () => {
  it("has twelve equal columns, and a class for every width a section can ask for, 1 to 12", () => {
    expect(styles).toMatch(/\.rp-grid \{[^}]*grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/);
    for (let n = 1; n <= 12; n++) expect(styles).toContain(`.rp-span-${n} { grid-column: span ${n}; }`);
    expect(styles).not.toContain(".rp-span-13");
    expect(styles).not.toContain(".rp-span-0 ");
  });

  it("narrows by the report's own width: below about 1,000px a section narrower than half takes half, and below about 680px every one takes the whole width", () => {
    expect(styles).toMatch(/\.rp-body \{ container-type: inline-size; \}/);
    expect(styles).toMatch(/@container \(max-width: 1000px\) \{ \.rp-span-1, \.rp-span-2, \.rp-span-3, \.rp-span-4, \.rp-span-5 \{ grid-column: span 6; \} \}/);
    expect(styles).toMatch(/@container \(max-width: 680px\) \{ \.rp-grid > \* \{ grid-column: span 12; \} \}/);
    expect(styles.indexOf("@container (max-width: 1000px)")).toBeGreaterThan(styles.indexOf(".rp-span-12 {"));      // later, so it wins over the widths above it
  });

  it("takes the sidebar's navigation look off a chart's breadcrumb, which is a nav element", () => {
    expect(styles).toMatch(/nav\.chart-crumbs \{ background: none; border: 0; padding: 0;/);
  });
});

describe("a hierarchy drawn as a table", () => {
  it("indents a child by its depth, up to the deepest a hierarchy may be, and marks a parent", () => {
    for (let n = 1; n <= 8; n++) expect(styles).toContain(`.rp-depth-${n} { padding-left: ${n * 20}px; }`);
    expect(styles).toContain(".lf-table tr.rp-parent td { font-weight: 600; }");
  });
});


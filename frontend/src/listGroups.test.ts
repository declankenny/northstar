import { afterEach, describe, expect, it } from "vitest";
import type { ListRow } from "./api";
import { COLLAPSED, groupId, groupLabel, groupSummary, isCollapsed, OPEN, sections, toggled } from "./listGroups";
import { setLocale, US_ENGLISH } from "./locale";

const row = (id: number, group: unknown, count: number, before = 0): ListRow => ({ _id: id, _links: {}, _group: group, _group_count: count, _group_before: before });

afterEach(() => setLocale(null));

describe("the rows of a page cut into groups", () => {
  it("makes one section for each run of rows of one group, with the group's size across all pages and how many are on this page", () => {
    const found = sections([row(1, "Checking", 3), row(2, "Checking", 3), row(3, "Savings", 9), row(4, "Savings", 9)]);
    expect(found.map((s) => [s.value, s.total, s.here, s.rows.map((r) => r._id)])).toEqual([["Checking", 3, 2, [1, 2]], ["Savings", 9, 2, [3, 4]]]);
  });

  it("says a page that opens on a group that began on the page before continues it, and no other section does", () => {
    const found = sections([row(5, "Savings", 9, 5), row(6, "Savings", 9, 6), row(7, "Term", 2, 0)]);
    expect(found.map((s) => s.continued)).toEqual([true, false]);
    expect(sections([row(1, "Savings", 9, 0)])[0].continued).toBe(false);          // the first rows of a group
    expect(sections([row(1, "A", 2, 0), row(2, "B", 5, 3)])[1].continued).toBe(false);   // only the page's first section can continue
  });

  it("keeps a group with no value apart from a group called null, and a number apart from its text", () => {
    const found = sections([row(1, "null", 1), row(2, "none", 1), row(3, null, 2), row(4, null, 2), row(5, 1, 1), row(6, "1", 1)]);
    expect(found.map((s) => s.id)).toEqual([groupId("null"), groupId("none"), groupId(null), groupId(1)]);
    expect(new Set([groupId("null"), groupId("none"), groupId(null), groupId(undefined) === groupId(null) ? "same" : "x"]).size).toBe(4);
    expect(groupId(null)).not.toBe(groupId("null"));
    expect(groupId(null)).not.toBe(groupId("none"));                                  // whatever name the empty group is stored under
    expect(found[2].here).toBe(2);
    expect(sections([])).toEqual([]);
  });

  it("does not change the rows it was given", () => {
    const rows = [row(1, "A", 1)];
    sections(rows);
    expect(rows).toEqual([row(1, "A", 1)]);
  });
});

describe("what the group header says beside the name", () => {
  const section = (total: number, here: number) => ({ id: "x", value: "x", total, here, continued: false, rows: [] });

  it("counts the rows, and says how many are on this page only when the group goes on to another", () => {
    expect(groupSummary(section(1, 1))).toBe("1 row");
    expect(groupSummary(section(3, 3))).toBe("3 rows");
    expect(groupSummary(section(9, 4))).toBe("9 rows (4 on this page)");
    expect(groupSummary(section(1234, 25))).toBe("1,234 rows (25 on this page)");
  });
});

describe("what a group is called", () => {
  it("writes a value as its column writes it: dates in the person's format, Yes and No, numbers with their marks", () => {
    expect(groupLabel("date", null, "2026-04-20")).toBe("Apr 20, 2026");
    expect(groupLabel("timestamp", null, "2026-04-20")).toBe("Apr 20, 2026");        // a timestamp is grouped by its UTC date
    expect(groupLabel("yes_no", null, 1)).toBe("Yes");
    expect(groupLabel("yes_no", null, 0)).toBe("No");
    expect(groupLabel("text", null, "Savings")).toBe("Savings");
    expect(groupLabel("choice", null, "Open")).toBe("Open");
    expect(groupLabel("integer", null, 1234)).toBe("1,234");
    expect(groupLabel("decimal", 2, 1999)).toBe("19.99");
    setLocale({ ...US_ENGLISH, tag: "de-DE", decimal_mark: ",", group_mark: "." });
    expect(groupLabel("decimal", 2, 1999)).toBe("19,99");
  });

  it("has no name for a group with no value, which the page calls No value", () => {
    expect(groupLabel("text", null, null)).toBeNull();
    expect(groupLabel("date", null, undefined)).toBeNull();
  });

  it("writes the value plainly when the column's kind is not known, as when the column is not shown and the list has not said its columns yet", () => {
    expect(groupLabel(undefined, null, "Savings")).toBe("Savings");
  });
});

describe("which groups are collapsed", () => {
  it("starts with every group open, and a press of a header closes that group and a second opens it", () => {
    expect(isCollapsed(OPEN, "a")).toBe(false);
    const closed = toggled(OPEN, "a");
    expect(isCollapsed(closed, "a")).toBe(true);
    expect(isCollapsed(closed, "b")).toBe(false);
    expect(isCollapsed(toggled(closed, "a"), "a")).toBe(false);
  });

  it("collapses every group, those on other pages too, until one is opened", () => {
    expect(isCollapsed(COLLAPSED, "never seen")).toBe(true);
    const one = toggled(COLLAPSED, "a");
    expect(isCollapsed(one, "a")).toBe(false);
    expect(isCollapsed(one, "b")).toBe(true);
    expect(isCollapsed(toggled(one, "a"), "a")).toBe(true);
  });

  it("does not change the state it was given", () => {
    toggled(OPEN, "a");
    expect(OPEN.except.size).toBe(0);
    toggled(COLLAPSED, "a");
    expect(COLLAPSED.except.size).toBe(0);
  });
});

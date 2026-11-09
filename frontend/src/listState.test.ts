import { describe, expect, it } from "vitest";
import { listAddress, listQuery, listRequest, parseListView, sortedBy, withFilters, withPage, withSearch, type ListView } from "./listState";

const DEFAULT: ListView = { page: 1, sort: null, search: "", filters: null };

describe("a list's view in the address", () => {
  it("is the default view when the address says nothing", () => {
    expect(parseListView("")).toEqual(DEFAULT);
    expect(listQuery(DEFAULT)).toBe("");
    expect(listAddress("/balances", DEFAULT)).toBe("/balances");
  });

  it("reads a sort, a page and a search, and writes them back the same", () => {
    const view = parseListView("?sort=-account&page=3&q=test%20note");
    expect(view).toEqual({ page: 3, sort: { field: "account", direction: "desc" }, search: "test note", filters: null });
    expect(parseListView(listQuery(view))).toEqual(view);
    expect(parseListView("?sort=as_of_date")).toEqual({ ...DEFAULT, sort: { field: "as_of_date", direction: "asc" } });
  });

  it("keeps a field with dots, which is how a column of a related record is named", () => {
    expect(parseListView("?sort=-account.currency").sort).toEqual({ field: "account.currency", direction: "desc" });
    expect(listQuery({ ...DEFAULT, sort: { field: "account.currency", direction: "asc" } })).toBe("?sort=account.currency");
  });

  it("falls back to the default for anything malformed, because an address is typed and pasted", () => {
    for (const bad of ["?page=0", "?page=-2", "?page=abc", "?page=2.5", "?page=", "?sort=", "?sort=-", "?q="]) {
      expect(parseListView(bad)).toEqual(DEFAULT);
    }
    expect(parseListView(`?sort=${"x".repeat(201)}`).sort).toBeNull();
    expect(parseListView(`?q=${"x".repeat(150)}`).search).toHaveLength(100);
  });

  it("writes only what is not the default, so a plain list has a plain address", () => {
    expect(listQuery(DEFAULT)).toBe("");
    expect(listQuery({ ...DEFAULT, page: 2 })).toBe("?page=2");
    expect(listQuery({ ...DEFAULT, search: "a b&c" })).toBe("?q=a+b%26c");
  });
});

describe("changing the view", () => {
  it("sorts ascending first, and reverses a column that is already the sort", () => {
    const first = sortedBy(DEFAULT, "date");
    expect(first.sort).toEqual({ field: "date", direction: "asc" });
    expect(sortedBy(first, "date").sort).toEqual({ field: "date", direction: "desc" });
    expect(sortedBy(sortedBy(first, "date"), "date").sort).toEqual({ field: "date", direction: "asc" });
    expect(sortedBy(first, "account").sort).toEqual({ field: "account", direction: "asc" }); // another column starts ascending
    expect(sortedBy(first, "date", "desc").sort).toEqual({ field: "date", direction: "desc" }); // the menu names a direction
  });

  it("goes back to the first page when the sort or the search changes, and never to a page before the first", () => {
    const later: ListView = { ...DEFAULT, page: 4 };
    expect(sortedBy(later, "date").page).toBe(1);
    expect(withSearch(later, "x")).toEqual({ ...DEFAULT, search: "x" });
    expect(withPage(later, 5).page).toBe(5);
    expect(withPage(later, 0).page).toBe(1);
  });

  it("asks the server only for what the view says", () => {
    expect(listRequest(DEFAULT)).toEqual({ page: 1 });
    expect(listRequest({ ...DEFAULT, page: 2, sort: { field: "date", direction: "desc" }, search: "x" }, 50))
      .toEqual({ page: 2, sort: { field: "date", direction: "desc" }, search: "x", page_size: 50 });
  });
});

describe("filters in the address", () => {
  const TYPE = { field: "account.type", operator: "is_any_of", value: [3, 4] };
  const DATE = { field: "as_of_date", operator: "after", value: "2025-12-31" };

  it("is no filter at all, so the list's default applies, when the address names none", () => {
    expect(parseListView("?page=2").filters).toBeNull();
    expect(listRequest(DEFAULT)).toEqual({ page: 1 });
    expect("filters" in listRequest(DEFAULT)).toBe(false);
  });

  it("carries conditions as JSON and reads them back the same, values and all", () => {
    const view = { ...DEFAULT, filters: [TYPE, DATE] };
    const query = listQuery(view);
    expect(query).toBe(`?filters=${encodeURIComponent(JSON.stringify([TYPE, DATE]))}`);
    expect(parseListView(query)).toEqual(view);
    expect(listRequest(view).filters).toEqual([TYPE, DATE]);
  });

  it("keeps an empty list of conditions, because that is a filter cleared on purpose and the default must not come back", () => {
    const cleared = { ...DEFAULT, filters: [] };
    expect(listQuery(cleared)).toBe("?filters=%5B%5D");
    expect(parseListView("?filters=%5B%5D").filters).toEqual([]);
    expect(listRequest(cleared)).toEqual({ page: 1, filters: [] });
  });

  it("treats anything that is not a list of conditions as none, because an address is typed and pasted", () => {
    for (const bad of ["nope", "{}", "3", "null", "[1]", "[null]", '[{"field":1,"operator":"x"}]', '[{"field":"a"}]', '[["a","b"]]', "[{"]) {
      expect(parseListView(`?filters=${encodeURIComponent(bad)}`).filters).toBeNull();
    }
    expect(parseListView(`?filters=${"x".repeat(20_001)}`).filters).toBeNull();
  });

  it("goes back to the first page when the filters change, and can hand back to the default", () => {
    const later = { ...DEFAULT, page: 4, filters: [DATE] };
    expect(withFilters(later, [TYPE])).toEqual({ ...DEFAULT, page: 1, filters: [TYPE] });
    expect(withFilters(later, null).filters).toBeNull();
  });
});

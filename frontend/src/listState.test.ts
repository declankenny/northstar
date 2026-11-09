import { describe, expect, it } from "vitest";
import { listAddress, listQuery, listRequest, parseListView, sortedBy, withPage, withSearch, type ListView } from "./listState";

const DEFAULT: ListView = { page: 1, sort: null, search: "" };

describe("a list's view in the address", () => {
  it("is the default view when the address says nothing", () => {
    expect(parseListView("")).toEqual(DEFAULT);
    expect(listQuery(DEFAULT)).toBe("");
    expect(listAddress("/balances", DEFAULT)).toBe("/balances");
  });

  it("reads a sort, a page and a search, and writes them back the same", () => {
    const view = parseListView("?sort=-account&page=3&q=test%20note");
    expect(view).toEqual({ page: 3, sort: { field: "account", direction: "desc" }, search: "test note" });
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
    expect(listQuery({ page: 1, sort: null, search: "" })).toBe("");
    expect(listQuery({ page: 2, sort: null, search: "" })).toBe("?page=2");
    expect(listQuery({ page: 1, sort: null, search: "a b&c" })).toBe("?q=a+b%26c");
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
    const later: ListView = { page: 4, sort: null, search: "" };
    expect(sortedBy(later, "date").page).toBe(1);
    expect(withSearch(later, "x")).toEqual({ page: 1, sort: null, search: "x" });
    expect(withPage(later, 5).page).toBe(5);
    expect(withPage(later, 0).page).toBe(1);
  });

  it("asks the server only for what the view says", () => {
    expect(listRequest(DEFAULT)).toEqual({ page: 1 });
    expect(listRequest({ page: 2, sort: { field: "date", direction: "desc" }, search: "x" }, 50))
      .toEqual({ page: 2, sort: { field: "date", direction: "desc" }, search: "x", page_size: 50 });
  });
});

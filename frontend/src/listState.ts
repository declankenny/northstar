import type { Condition, ListRequest } from "./api";

/** The part of a list's view that lives in the page address, so a refresh, a copied link, Back and returning from a record all
 *  restore it: `?sort=-date&page=2&q=savings`. A descending sort is the field with a minus in front. Anything missing or
 *  malformed is the list's own default, never an error, because an address is typed and pasted by people. */
export type ListSort = { field: string; direction: "asc" | "desc" };
/** `filters` is null when the address names none, so the list opens with the person's default filter; an empty list is a filter that
 *  was cleared on purpose, so the default does not come back by itself. */
export type ListView = { page: number; sort: ListSort | null; search: string; filters: Condition[] | null; group: string | null };

export const MAX_SEARCH = 100;
const MAX_FIELD = 200;
const MAX_FILTERS_TEXT = 20_000; // the longest filter the server saves; a longer address is not a filter

/** The conditions in an address, or null when there are none or they are not a list of conditions: an address is typed and pasted. */
function parseFilters(text: string | null): Condition[] | null {
  if (text === null || text.length > MAX_FILTERS_TEXT) return null;
  try {
    const parsed: unknown = JSON.parse(text);
    if (!Array.isArray(parsed)) return null;
    const ok = parsed.every((c) => c !== null && typeof c === "object" && !Array.isArray(c)
      && typeof (c as Condition).field === "string" && typeof (c as Condition).operator === "string");
    return ok ? (parsed as Condition[]) : null;
  } catch {
    return null;
  }
}

export function parseListView(search: string): ListView {
  const params = new URLSearchParams(search);
  const page = Number(params.get("page"));
  const sort = params.get("sort") ?? "";
  const group = params.get("group") ?? "";
  const field = sort.startsWith("-") ? sort.slice(1) : sort;
  return {
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    sort: field !== "" && field.length <= MAX_FIELD ? { field, direction: sort.startsWith("-") ? "desc" : "asc" } : null,
    search: (params.get("q") ?? "").slice(0, MAX_SEARCH),
    filters: parseFilters(params.get("filters")),
    group: group !== "" && group.length <= MAX_FIELD ? group : null,
  };
}

/** The query string for a view: empty for the default view, so the address of a list is plain until someone changes it. */
export function listQuery(view: ListView): string {
  const params = new URLSearchParams();
  if (view.sort) params.set("sort", (view.sort.direction === "desc" ? "-" : "") + view.sort.field);
  if (view.page > 1) params.set("page", String(view.page));
  if (view.search !== "") params.set("q", view.search);
  if (view.filters !== null) params.set("filters", JSON.stringify(view.filters));
  if (view.group) params.set("group", view.group);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

export const listAddress = (path: string, view: ListView) => path + listQuery(view);

/** Sort by a column, back on the first page. With no direction a column that is already the sort is reversed. */
export function sortedBy(view: ListView, field: string, direction?: "asc" | "desc"): ListView {
  const next = direction ?? (view.sort?.field === field && view.sort.direction === "asc" ? "desc" : "asc");
  return { ...view, page: 1, sort: { field, direction: next } };
}

export const withPage = (view: ListView, page: number): ListView => ({ ...view, page: Math.max(1, page) });

/** A new search text, back on the first page. */
export const withSearch = (view: ListView, search: string): ListView => ({ ...view, page: 1, search: search.slice(0, MAX_SEARCH) });

/** New conditions (or null for the person's default), back on the first page. */
export const withFilters = (view: ListView, filters: Condition[] | null): ListView => ({ ...view, page: 1, filters });

/** Group by a column (or, with null, ungroup), back on the first page. */
export const withGroup = (view: ListView, group: string | null): ListView => ({ ...view, page: 1, group });

/** The request that asks the server for this view. `pageSize` is only sent once the person has chosen one on this page. */
export function listRequest(view: ListView, pageSize?: number): ListRequest {
  const request: ListRequest = { page: view.page };
  if (view.sort) request.sort = view.sort;
  if (view.search !== "") request.search = view.search;
  if (view.filters !== null) request.filters = view.filters;
  if (view.group) request.group = view.group;
  if (pageSize !== undefined) request.page_size = pageSize;
  return request;
}

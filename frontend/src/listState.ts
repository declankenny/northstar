import type { ListRequest } from "./api";

/** The part of a list's view that lives in the page address, so a refresh, a copied link, Back and returning from a record all
 *  restore it: `?sort=-date&page=2&q=savings`. A descending sort is the field with a minus in front. Anything missing or
 *  malformed is the list's own default, never an error, because an address is typed and pasted by people. */
export type ListSort = { field: string; direction: "asc" | "desc" };
export type ListView = { page: number; sort: ListSort | null; search: string };

export const MAX_SEARCH = 100;
const MAX_FIELD = 200;

export function parseListView(search: string): ListView {
  const params = new URLSearchParams(search);
  const page = Number(params.get("page"));
  const sort = params.get("sort") ?? "";
  const field = sort.startsWith("-") ? sort.slice(1) : sort;
  return {
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    sort: field !== "" && field.length <= MAX_FIELD ? { field, direction: sort.startsWith("-") ? "desc" : "asc" } : null,
    search: (params.get("q") ?? "").slice(0, MAX_SEARCH),
  };
}

/** The query string for a view: empty for the default view, so the address of a list is plain until someone changes it. */
export function listQuery(view: ListView): string {
  const params = new URLSearchParams();
  if (view.sort) params.set("sort", (view.sort.direction === "desc" ? "-" : "") + view.sort.field);
  if (view.page > 1) params.set("page", String(view.page));
  if (view.search !== "") params.set("q", view.search);
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

/** The request that asks the server for this view. `pageSize` is only sent once the person has chosen one on this page. */
export function listRequest(view: ListView, pageSize?: number): ListRequest {
  const request: ListRequest = { page: view.page };
  if (view.sort) request.sort = view.sort;
  if (view.search !== "") request.search = view.search;
  if (pageSize !== undefined) request.page_size = pageSize;
  return request;
}

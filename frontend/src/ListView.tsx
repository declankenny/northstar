import {
  createColumnHelper, rowPaginationFeature, rowSortingFeature, tableFeatures, useTable,
  type PaginationState, type Row, type SortingState,
} from "@tanstack/react-table";
import { Fragment, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type Choices, type Condition, exportList, fetchList, fetchListChoices, fetchListFields, type ListColumn, type ListPage, type ListRow, saveListColumns,
  saveListPageSize,
} from "./api";
import { FilterDrawer } from "./FilterDrawer";
import { describe, flatten } from "./listFilters";
import { formatCell, isNumeric } from "./listFormat";
import { COLLAPSED, type Collapsing, groupLabel, groupSummary, isCollapsed, OPEN, sections, toggled } from "./listGroups";
import { listAddress, listRequest, parseListView, sortedBy, withFilters, withGroup, withPage, withSearch } from "./listState";
import { formatInteger } from "./locale";
import { RowMenu, type MenuItem } from "./RowMenu";
import { Link, navigate, replaceAddress, usePath, useSearch } from "./router";
import { useRequest } from "./useRequest";

// What a list needs that only its own page knows. A list is data on the server; this is the little that cannot be: how a cell is
// drawn when the default is not enough, and what a row's menu does (its dialogs are React).
export type ListConfig = {
  emptyText?: string;                                                      // what an empty list says, before anything is added
  cell?: Record<string, (row: ListRow, page: ListPage) => ReactNode>;     // a column drawn its own way, by key
  actions?: (row: ListRow) => MenuItem[];                                  // a row's menu; an item can be disabled, with its reason
  rowLabel?: (row: ListRow) => string;                                     // what the row's menu button is called
  title?: string;                                                          // what the list is called in its filter drawer
  isAdmin?: boolean;                                                       // admins can save a filter for everyone
};

const features = tableFeatures({ rowSortingFeature, rowPaginationFeature });
const helper = createColumnHelper<typeof features, ListRow>();
const NO_ROWS: ListRow[] = [];
const NO_CONDITIONS: Condition[] = [];
const NO_KEYS: string[] = [];
const PAGE_SIZES = [10, 25, 50, 100];
const SEARCH_DELAY = 300; // milliseconds after the last key before the server is asked

/** The same array while the columns are the same ones, so a new answer to the same question does not rebuild the table. */
function useSameColumns(next: ListColumn[] | undefined): ListColumn[] {
  const kept = useRef<ListColumn[]>([]);
  const same = next && next.length === kept.current.length
    && next.every((column, i) => column.key === kept.current[i].key && column.path_label === kept.current[i].path_label);
  if (next && !same) kept.current = next;
  return kept.current;
}

/** The column's menu: the ways to sort that are not a click, and Group by. On the column the list is grouped by it offers Expand all,
 *  Collapse all and Ungroup instead; on a column that cannot be grouped (an amount) there is no Group by. Filter and Hide join it later. */
function HeaderMenu({ label, grouped, groupable, onAscending, onDescending, onGroup, onUngroup, onExpandAll, onCollapseAll }: {
  label: string; grouped: boolean; groupable: boolean; onAscending: () => void; onDescending: () => void;
  onGroup: () => void; onUngroup: () => void; onExpandAll: () => void; onCollapseAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("click", close); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <>
      <button className={open ? "th-menu on" : "th-menu"} aria-label={`Column menu for ${label}`} aria-haspopup="menu"
        aria-expanded={open} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>▾</button>
      {open && (
        <div className="menu" role="menu">
          <button role="menuitem" onClick={onAscending}>Sort ascending</button>
          <button role="menuitem" onClick={onDescending}>Sort descending</button>
          {grouped ? (
            <>
              <button role="menuitem" onClick={onExpandAll}>Expand all</button>
              <button role="menuitem" onClick={onCollapseAll}>Collapse all</button>
              <button role="menuitem" onClick={onUngroup}>Ungroup</button>
            </>
          ) : groupable && <button role="menuitem" onClick={onGroup}>Group by {label}</button>}
        </div>
      )}
    </>
  );
}

const CAP = 40;       // the cells are capped at this many characters (the stylesheet says it in ch); more of a text shows on hover

/** The whole text of a cell that is long enough to be cut off, for its tooltip. A cell drawn its own way has no such text. */
function fullText(column: ListColumn, row: ListRow, config: ListConfig): string | undefined {
  if (config.cell?.[column.key]) return undefined;
  const text = formatCell(column, row[column.key]);
  return text !== null && text.length > CAP ? text : undefined;
}

function cellContent(column: ListColumn, row: ListRow, page: ListPage, config: ListConfig): ReactNode {
  const custom = config.cell?.[column.key];
  if (custom) return custom(row, page);
  const text = formatCell(column, row[column.key]);
  if (text === null) return <span className="m">—</span>;
  const href = row._links[column.key];
  return href ? <Link className="name" to={href}>{text}</Link> : text;
}

/** One list, any list: the server does the sorting, searching and paging, and the address says which view this is. A page that changes
 *  what the list holds (an Add button) raises `refreshKey`, and the rows are read again in place: the sort, filters, page and drawer stay.
 *
 *  A fixed list (`fixed`) is one a person cannot change, on a page that has its own address: it has no search, Filters, Columns, groups
 *  or export, and its sort and page are kept in the page (React state) and not in the address. `params` are what its scope needs. */
export function ListView({ listKey, config = {}, refreshKey = 0, fixed }: {
  listKey: string; config?: ListConfig; refreshKey?: number; fixed?: { params: Record<string, number> };
}) {
  const [drawer, setDrawer] = useState<"filters" | "columns" | null>(null);   // which tab the open drawer starts on
  const opener = useRef<HTMLButtonElement | null>(null);                    // the button that opened it, to give focus back to
  const [columnsChanged, setColumnsChanged] = useState(0);                    // counts the person's changes to their columns, which are not in the address
  const [named, setNamed] = useState<Map<string, Choices>>(new Map()); // what a relation's records are called, for chips and the drawer
  const asked = useRef(new Set<string>());
  const path = usePath();
  const address = useSearch();
  const [kept, setKept] = useState(() => parseListView(""));                  // a fixed list's sort and page
  const view = useMemo(() => (fixed ? kept : parseListView(address)), [fixed, kept, address]);
  const [size, setSize] = useState<number | undefined>(undefined); // chosen on this page; before that the server uses the person's own
  const [text, setText] = useState(view.search);
  const [problem, setProblem] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const written = useRef(view.search);                              // the search text this page last put in the address
  const [collapsing, setCollapsing] = useState<Collapsing>(OPEN);     // which groups are collapsed: kept for the visit, not in the address
  useEffect(() => { setCollapsing(OPEN); }, [view.group]);            // another grouping is a new set of groups

  const { data: page, error, loading, reload } = useRequest(
    (signal) => fetchList(listKey, fixed ? { ...listRequest(view), params: fixed.params } : listRequest(view, size), signal),
    [listKey, view.page, view.sort?.field, view.sort?.direction, view.search, view.group, size, JSON.stringify(view.filters), columnsChanged, refreshKey,
      JSON.stringify(fixed?.params)],
  );

  const go = (next: typeof view) => { if (fixed) setKept(next); else navigate(listAddress(path, next)); };

  // The columns that can be filtered by: needed to say a filter in words and to build one.
  const { data: tree, error: treeError } = useRequest((signal) => fetchListFields(listKey, signal), [listKey], { skip: !!fixed });
  const nodes = useMemo(() => new Map(flatten(tree).map((n) => [n.key, n])), [tree]);
  const ensureChoices = useCallback((field: string) => {
    const id = `${listKey}/${field}`;
    if (asked.current.has(id)) return;
    asked.current.add(id);
    fetchListChoices(listKey, field).then(
      (choices) => setNamed((before) => new Map(before).set(field, choices)),
      () => asked.current.delete(id),
    );
  }, [listKey]);
  useEffect(() => { asked.current = new Set(); setNamed(new Map()); }, [listKey]);
  const applied: Condition[] = page?.filters ?? NO_CONDITIONS;
  useEffect(() => { applied.forEach((c) => { if (nodes.get(c.field)?.choices === "records") ensureChoices(c.field); }); }, [applied, nodes, ensureChoices]);

  // The search box follows the address (Back, a link), and the address follows the box once typing pauses, without a history
  // entry for every letter. A change this page made itself is not copied back, which would undo what was typed in the meantime.
  useEffect(() => { if (view.search !== written.current) setText(view.search); }, [view.search]);
  useEffect(() => {
    if (text === view.search) return;
    const timer = window.setTimeout(() => {
      written.current = text.slice(0, 100);
      replaceAddress(listAddress(path, withSearch(view, text)));
    }, SEARCH_DELAY);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the pause restarts with the text, not with every change to the view
  }, [text]);

  /** The view as a CSV file: the list's own request, which the server answers with every matching row. */
  const exportView = () => {
    setExporting(true);
    setProblem(null);
    exportList(listKey, listRequest(view, size))
      .catch((e: Error) => setProblem(`The list could not be exported. ${e.message}`))
      .finally(() => setExporting(false));
  };

  const changeSize = (next: number) => {
    setSize(next);
    setProblem(null);
    saveListPageSize(listKey, next).catch((e: Error) => setProblem(`The number of rows could not be remembered. ${e.message}`));
    go(withPage(view, 1));
  };

  const shown = view.sort ?? page?.sort ?? null; // the list's own sort shows too, so a person can see what the order is
  const sorting: SortingState = shown ? [{ id: shown.field, desc: shown.direction === "desc" }] : [];
  const pagination: PaginationState = { pageIndex: (page?.page ?? view.page) - 1, pageSize: page?.page_size ?? size ?? 25 };
  const columnList = useSameColumns(page?.columns);
  const columns = useMemo(
    () => columnList.map((column) => helper.accessor((row) => row[column.key] as unknown, { id: column.key, header: column.path_label })),
    [columnList],
  );
  const table = useTable({
    features, columns, data: page?.rows ?? NO_ROWS, getRowId: (row) => String(row._id),
    manualSorting: true, manualPagination: true, rowCount: page?.total ?? 0,
    enableMultiSort: false, enableSortingRemoval: false, sortDescFirst: false, // a click sorts ascending, a second click reverses
    state: { sorting, pagination },
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater;
      const first = next[0];
      go(first ? sortedBy(view, first.id, first.desc ? "desc" : "asc") : { ...view, page: 1, sort: null });
    },
    onPaginationChange: (updater) => {
      const next = typeof updater === "function" ? updater(pagination) : updater;
      if (next.pageSize !== pagination.pageSize) changeSize(next.pageSize);
      else go(withPage(view, next.pageIndex + 1));
    },
  });

  const byKey = new Map(columnList.map((column) => [column.key, column]));
  const rowsById = new Map(table.getRowModel().rows.map((row) => [row.original._id, row]));
  /** One row of the table: its cells, and its menu when the list has row actions. */
  const bodyRow = (row: Row<typeof features, ListRow> | undefined) => {
    if (!row || !page) return null;
    return (
      <tr key={row.id} className="row">
        {row.getAllCells().map((cell) => {
          const column = byKey.get(cell.column.id);
          return column && (
            <td key={cell.id} className={isNumeric(column) ? "r" : ""} title={fullText(column, row.original, config)}>
              {cellContent(column, row.original, page, config)}
            </td>
          );
        })}
        {config.actions && (
          <td className="k">
            <RowMenu label={`Actions for ${config.rowLabel?.(row.original) ?? `row ${row.original._id}`}`}
              items={config.actions(row.original)} />
          </td>
        )}
      </tr>
    );
  };
  const shownKeys = useMemo(() => (page ? page.columns.map((c) => c.key) : NO_KEYS), [page]);
  const skippedKeys = useMemo(() => (page ? page.skipped_columns.flatMap((s) => (s.field ? [s.field] : [])) : NO_KEYS), [page]);
  const groupColumn = view.group ? byKey.get(view.group) : undefined;
  const groupNode = view.group ? nodes.get(view.group) : undefined;
  const groupName = groupColumn?.path_label ?? groupNode?.path_label ?? view.group;
  const groupKind = groupColumn?.kind ?? groupNode?.kind;
  const groupScale = groupColumn?.scale ?? groupNode?.scale ?? null;
  const columnCount = columnList.length + (config.actions ? 1 : 0);
  /** The button, with how many rows the file will have beside it. It is there for an empty result too, which gives the headers alone. */
  const exportButton = page && (
    <>
      <button className="btn ghost small" disabled={exporting} onClick={exportView}>{exporting ? "Exporting…" : "Export CSV"}</button>
      <span className="m">{formatInteger(page.total)} {page.total === 1 ? "row" : "rows"}</span>
    </>
  );
  const first = page && page.rows.length > 0 ? (page.page - 1) * page.page_size + 1 : 0;
  const sizes = PAGE_SIZES.includes(pagination.pageSize) ? PAGE_SIZES : [...PAGE_SIZES, pagination.pageSize].sort((a, b) => a - b);

  if (fixed) {
    const sortedKey = shown?.field;
    return (
      <>
        {error && (
          <p className="notice bad" role="alert">Could not load the list. {error}{" "}
            <button className="link" onClick={reload}>Try again</button></p>
        )}
        {!page ? (
          !error && <p className="empty pad">Loading…</p>
        ) : page.total === 0 ? (
          <p className="empty pad">{config.emptyText ?? "There is nothing to show yet."}</p>
        ) : (
          <>
            <div className="hist" aria-busy={loading}>
              <table className={loading ? "num lf-busy" : "num"}>
                <thead>
                  {table.getHeaderGroups().map((group) => (
                    <tr key={group.id}>
                      {group.headers.map((header) => {
                        const column = byKey.get(header.column.id);
                        const sorted = header.column.getIsSorted();
                        return (
                          <th key={header.id} className={column && isNumeric(column) ? "r" : ""}
                            aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                            <button className="th-btn" onClick={header.column.getToggleSortingHandler()}>
                              {column?.path_label ?? header.column.id}
                              {header.column.id === sortedKey && <span className="sort" aria-hidden="true">{sorted === "asc" ? "▲" : "▼"}</span>}
                            </button>
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody>{table.getRowModel().rows.map((row) => bodyRow(row))}</tbody>
              </table>
            </div>
            {page.pages > 1 && (
              <div className="lf-foot">
                <span>{formatInteger(first)}–{formatInteger(first + page.rows.length - 1)} of {formatInteger(page.total)}</span>
                <span>Page {formatInteger(page.page)} of {formatInteger(page.pages)}</span>
                <button className="btn ghost small" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>Previous</button>
                <button className="btn ghost small" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>Next</button>
              </div>
            )}
          </>
        )}
      </>
    );
  }

  return (
    <div className="lf">
      <div className="lf-bar">
        <input className="lf-search" aria-label="Search" placeholder="Search" value={text} maxLength={100}
          onChange={(e) => setText(e.target.value)} />
        <button className="btn ghost small" disabled={!tree} aria-haspopup="dialog" onClick={(e) => { opener.current = e.currentTarget; setDrawer("filters"); }}>
          Filters{applied.length > 0 ? ` (${applied.length})` : ""}</button>
        <button className="btn ghost small" disabled={!tree || !page} aria-haspopup="dialog" onClick={(e) => { opener.current = e.currentTarget; setDrawer("columns"); }}>
          Columns</button>
        <span className="grow" />
        {page && <span className="m lf-count">{formatInteger(page.total)} matching</span>}
      </div>

      {view.group && (
        <div className="lf-chips">
          <span className="lf-chip">Grouped by {groupName}
            <button aria-label="Ungroup" onClick={() => go(withGroup(view, null))}>✕</button></span>
        </div>
      )}
      {applied.length > 0 && (
        <div className="lf-chips" role="list" aria-label="Filters applied">
          {applied.map((condition, i) => (
            <span className="lf-chip" role="listitem" key={condition.field}>
              {describe(nodes.get(condition.field), condition, named.get(condition.field))}
              <button aria-label={`Remove the filter: ${describe(nodes.get(condition.field), condition, named.get(condition.field))}`}
                onClick={() => go(withFilters(view, applied.filter((_, j) => j !== i)))}>✕</button>
            </span>
          ))}
          <button className="link" onClick={() => go(withFilters(view, []))}>Clear filters</button>
        </div>
      )}
      {page && page.skipped.length > 0 && (
        <p className="notice warn" role="status">
          {page.skipped.length === 1 ? "1 condition of your default filter was" : `${page.skipped.length} conditions of your default filter were`} left
          out because the list does not offer {page.skipped.length === 1 ? "that column" : "those columns"} any more.</p>
      )}
      {page && page.skipped_columns.length > 0 && (
        <p className="notice warn" role="status">
          {page.skipped_columns.length === 1 ? "1 column of your choice was" : `${page.skipped_columns.length} columns of your choice were`} left
          out because the list does not offer {page.skipped_columns.length === 1 ? "it" : "them"} any more.</p>
      )}
      {treeError && <p className="notice bad" role="alert">Could not load the columns to filter by. {treeError}</p>}
      {error && (
        <p className="notice bad" role="alert">Could not load the list. {error}{" "}
          <button className="link" onClick={reload}>Try again</button></p>
      )}
      {problem && <p className="notice bad" role="alert">{problem}</p>}

      {!page ? (
        !error && <p className="empty">Loading…</p>
      ) : page.total === 0 ? (
        view.search !== "" || applied.length > 0 ? (
          <p className="empty">No rows match{view.search !== "" ? <> “{view.search}”</> : " the filters"}.{" "}
            {view.search !== "" && <button className="link" onClick={() => go(withSearch(view, ""))}>Clear the search</button>}{" "}
            {applied.length > 0 && <button className="link" onClick={() => go(withFilters(view, []))}>Clear the filters</button>}</p>
        ) : (
          <p className="empty">{config.emptyText ?? "There is nothing to show yet."}</p>
        )
      ) : (
        <>
          <div className="gcard lf-card" aria-busy={loading}>
            <table className={loading ? "num lf-table lf-busy" : "num lf-table"}>
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => {
                      const column = byKey.get(header.column.id);
                      const label = column?.path_label ?? header.column.id;        // "Account › Updated by": a related column says where it comes from
                      const sorted = header.column.getIsSorted();
                      return (
                        <th key={header.id} className={column && isNumeric(column) ? "r" : ""}
                          aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                          <button className="th-btn" onClick={header.column.getToggleSortingHandler()}>
                            {label}{sorted && <span className="sort" aria-hidden="true">{sorted === "asc" ? "▲" : "▼"}</span>}
                          </button>
                          <HeaderMenu label={label} grouped={view.group === header.column.id} groupable={column?.groupable ?? false}
                            onAscending={() => header.column.toggleSorting(false)} onDescending={() => header.column.toggleSorting(true)}
                            onGroup={() => go(withGroup(view, header.column.id))} onUngroup={() => go(withGroup(view, null))}
                            onExpandAll={() => setCollapsing(OPEN)} onCollapseAll={() => setCollapsing(COLLAPSED)} />
                        </th>
                      );
                    })}
                    {config.actions && <th />}
                  </tr>
                ))}
              </thead>
              <tbody>
                {view.group
                  ? sections(page.rows).map((section) => {
                      const open = !isCollapsed(collapsing, section.id);
                      const name = groupLabel(groupKind, groupScale, section.value);
                      return (
                        <Fragment key={`${section.id}-${section.rows[0]._id}`}>
                          <tr className="grp">
                            <td colSpan={columnCount}>
                              <button className="grp-btn" aria-expanded={open} onClick={() => setCollapsing(toggled(collapsing, section.id))}>
                                <span className="caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
                                {name === null ? <span className="none">No value</span> : <span className="name">{name}</span>}
                                <span className="n">{groupSummary(section)}</span>
                                {section.continued && <span className="cont">continued</span>}
                              </button>
                            </td>
                          </tr>
                          {open && section.rows.map((record) => bodyRow(rowsById.get(record._id)))}
                        </Fragment>
                      );
                    })
                  : table.getRowModel().rows.map((row) => bodyRow(row))}
              </tbody>
            </table>
          </div>
          <div className="lf-foot">
            <span>{formatInteger(first)}–{formatInteger(first + page.rows.length - 1)} of {formatInteger(page.total)}</span>
            <span>Page {formatInteger(page.page)} of {formatInteger(page.pages)}</span>
            <button className="btn ghost small" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>Previous</button>
            <button className="btn ghost small" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>Next</button>
            {exportButton}
            <span className="grow" />
            <label>Rows per page{" "}
              <select value={pagination.pageSize} onChange={(e) => table.setPageSize(Number(e.target.value))}>
                {sizes.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
        </>
      )}
      {page && page.total === 0 && <div className="lf-foot">{exportButton}</div>}
      {drawer && tree && (
        <FilterDrawer listKey={listKey} title={config.title ?? "List"} tree={tree} applied={applied} openedWith={page?.default_filter_id ?? null}
          isAdmin={config.isAdmin ?? false} choices={named} ensureChoices={ensureChoices} tab={drawer}
          columns={shownKeys} defaultColumns={page?.default_columns ?? NO_KEYS} skippedColumns={skippedKeys}
          onApply={(conditions, chosen) => {
            setDrawer(null); opener.current?.focus();
            // Only when the filters changed: applying new columns must not turn the default filter into one written in the address.
            if (JSON.stringify(conditions) !== JSON.stringify(applied)) go(withFilters(view, conditions));
            if (chosen === undefined) return;
            setProblem(null);
            saveListColumns(listKey, chosen).then(
              () => setColumnsChanged((n) => n + 1),
              (e: Error) => setProblem(`The columns could not be saved. ${e.message}`),
            );
          }}
          onClose={() => { setDrawer(null); opener.current?.focus(); }} />
      )}
    </div>
  );
}

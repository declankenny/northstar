import { useEffect, useRef, useState } from "react";
import type { Choices, Condition, FieldTree } from "./api";
import { ColumnsPanel } from "./ColumnsPanel";
import { DrawerFrame } from "./DrawerFrame";
import { FilterConditions } from "./FilterConditions";
import { LIST_WORDS } from "./filterWords";
import { columnChoice, sameColumns } from "./listColumns";
import { DeleteSavedFilter, SavedFiltersBar, useSavedFilters } from "./SavedFilters";
import { useFilterDraft } from "./useFilterDraft";

/** What the drawer needs from the list behind it. `choices` holds what a relation's records are called, once asked for. */
export type FilterDrawerProps = {
  listKey: string; title: string; tree: FieldTree; applied: Condition[];
  openedWith: number | null;                       // the saved filter the list opened with, so it shows as loaded
  isAdmin: boolean;                                // admins can save a filter for everyone
  choices: Map<string, Choices>; ensureChoices: (field: string) => void;
  columns: string[];                               // the keys of the columns the list shows now
  defaultColumns: string[];                        // and of the ones it shows when a person has chosen none
  skippedColumns: string[];                        // saved columns the list no longer offers, left out of `columns`
  tab: "filters" | "columns";                      // the tab the drawer opens on
  /** `columns` is what the server is to be told: nothing (undefined) when they are as they were, null to forget the choice. */
  onApply: (conditions: Condition[], columns: string[] | null | undefined) => void; onClose: () => void;
};

/** The drawer where a list's filters are made, applied and saved, and its columns chosen. It is the shared filter editor (the draft,
 *  the conditions, the frame) with the two things only a list has: saved filters and the Columns tab. What is typed here is a draft:
 *  nothing reaches the list until Apply changes, and Cancel throws it away. */
export function FilterDrawer(props: FilterDrawerProps) {
  const { listKey, title, tree, applied, openedWith, isAdmin, choices, ensureChoices, columns, defaultColumns, skippedColumns, onApply, onClose } = props;
  const [tab, setTab] = useState(props.tab);
  const [draftColumns, setColumns] = useState(columns);
  const touched = useRef(false);                       // the person has changed the columns, so a later answer from the list must not undo it
  const setDraftColumns = (next: string[]) => { touched.current = true; setColumns(next); };
  useEffect(() => { if (!touched.current) setColumns(columns); }, [columns]);   // the list had not answered yet when the drawer opened

  const filters = useFilterDraft(tree, applied, ensureChoices);
  const saved = useSavedFilters(listKey, openedWith, filters);
  const { draft, setDraft, valid, wire, setAttempted } = filters;

  const apply = () => (valid
    ? onApply(wire(), columns.length === 0 ? undefined : columnChoice(draftColumns, columns, defaultColumns))
    : (setAttempted(true), setTab("filters")));

  return (
    <DrawerFrame label={`${title} filters`} heading={LIST_WORDS.heading(title)} onApply={apply} onClose={onClose} escapeCloses={!saved.deleting}
      tabs={
        <div className="ranges lf-tabs">
          <button className={tab === "filters" ? "on" : ""} aria-current={tab === "filters" ? "true" : undefined} onClick={() => setTab("filters")}>Filters ({draft.length})</button>
          <button className={tab === "columns" ? "on" : ""} aria-current={tab === "columns" ? "true" : undefined} disabled={columns.length === 0}
            onClick={() => setTab("columns")}>Columns ({draftColumns.length})</button>
        </div>
      }
      footLeft={tab === "filters"
        ? <button className="link" onClick={() => { setDraft([]); saved.forget(); }}>Clear filters</button>
        : <button className="link" disabled={sameColumns(draftColumns, defaultColumns)} onClick={() => setDraftColumns(defaultColumns)}>Reset to default columns</button>}
      overlay={<DeleteSavedFilter s={saved} />}>
      {tab === "columns" && <ColumnsPanel tree={tree} keys={draftColumns} skipped={skippedColumns} onChange={setDraftColumns} />}
      {tab === "filters" && <>
        <SavedFiltersBar s={saved} isAdmin={isAdmin} />
        <FilterConditions tree={tree} filters={filters} choices={choices} words={LIST_WORDS} />
      </>}
    </DrawerFrame>
  );
}

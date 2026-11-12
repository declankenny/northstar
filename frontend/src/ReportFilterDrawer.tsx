import type { Choices, Condition, FieldTree } from "./api";
import { DrawerFrame } from "./DrawerFrame";
import { FilterConditions } from "./FilterConditions";
import { REPORT_WORDS } from "./filterWords";
import { useFilterDraft } from "./useFilterDraft";

/** The drawer where a report's filters are made: the lists' own condition editor, draft and Apply, with no saved filters and no Columns
 *  tab, so it asks the server for neither. A report is opened with its declared defaults every time, and what is applied here lives
 *  only in the current view. `tree` is what the report allows filtering by. */
export function ReportFilterDrawer({ title, tree, applied, choices, ensureChoices, onApply, onClose }: {
  title: string; tree: FieldTree; applied: Condition[]; choices: Map<string, Choices>; ensureChoices: (field: string) => void;
  onApply: (conditions: Condition[]) => void; onClose: () => void;
}) {
  const filters = useFilterDraft(tree, applied, ensureChoices);
  const { setDraft, valid, wire, setAttempted } = filters;
  return (
    <DrawerFrame label={`${title} filters`} heading={REPORT_WORDS.heading(title)} onApply={() => (valid ? onApply(wire()) : setAttempted(true))} onClose={onClose}
      footLeft={<button className="link" onClick={() => setDraft([])}>Clear filters</button>}>
      <FilterConditions tree={tree} filters={filters} choices={choices} words={REPORT_WORDS} />
    </DrawerFrame>
  );
}

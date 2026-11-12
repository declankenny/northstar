/** The words the filter editor says that depend on what is being filtered. A list says "column" and "row"; a report has no columns and its
 *  population is declared by the report, so its words name nothing. */
export type FilterWords = {
  heading: (title: string) => string;     // the drawer's heading
  empty: string;                          // shown when the draft has no conditions
  picker: string;                         // the label of the list of fields to add a condition on
  things: string;                         // what the fields are called in the picker's fold buttons: "columns" or "fields"
  gone: string;                           // beside a condition on a field that is not offered any more
  help: string;                           // the note at the foot of the conditions
};

const RULES = "Conditions combine with AND; several choices in one condition mean any of them. “is after” leaves out the date itself; “is between” includes both ends.";

export const LIST_WORDS: FilterWords = {
  heading: (title) => `${title} view`,
  empty: "No conditions. Every row is shown.",
  picker: "Columns to filter by",
  things: "columns",
  gone: "not a column of this list",
  help: `${RULES} Amounts are compared in each row’s own currency, so filter by Currency too when comparing across currencies.`,
};

export const REPORT_WORDS: FilterWords = {
  heading: (title) => `${title} filters`,
  empty: "No conditions. Nothing is filtered out.",
  picker: "Fields to filter by",
  things: "fields",
  gone: "not available for this report",
  help: RULES,
};

import type { Choices, Condition, FieldTree } from "../api";
import type { SectionKind, View } from "./views";

/** The contracts of the report endpoints (`/api/reports`). Money is integer minor units, dates are `YYYY-MM-DD` text, and nothing
 *  here is a chart configuration: a section names a view and the page decides how to draw it. */

export type ReportListItem = { key: string; title: string; description: string };

export type ParameterKind = "date" | "choice" | "integer";

/** A date parameter's rules, by name. `after` is strictly after the other parameter (an ordered pair of endpoints); `on_or_after`
 *  allows the same day (an inclusive range). The page can validate with these and needs no knowledge of any one report. */
export type ParameterRule = { rule: "not_future" } | { rule: "after"; other: string } | { rule: "on_or_after"; other: string };

export type ReportParameter = {
  key: string;
  label: string;
  kind: ParameterKind;
  /** Resolved by the server with its own `today`. The page sends every parameter explicitly; the server never fills one in. */
  default: string | number;
  choices: { value: string; label: string }[];
  minimum: number | null;
  maximum: number | null;
  rules: ParameterRule[]; // a date's rules; empty for any other kind
};

export type ReportSectionDeclaration = {
  key: string;
  kind: SectionKind;
  view: View;
  title: string;
  /** A hierarchy only: its leaves carry a size, and the server adds each parent's. */
  sized: boolean;
  /** How many of the page's 12 columns the section takes, 1 to 12: 12 is the whole width, 6 half, 4 a third, 3 a quarter. */
  columns: number;
};

/** `GET /api/reports/{key}`: public metadata only. */
export type ReportDefinition = {
  key: string;
  title: string;
  description: string;
  today: string; // the server's today(), so the page never reads the browser's clock
  parameters: ReportParameter[];
  sections: ReportSectionDeclaration[];
  filters: ReportFilters;
};

/** What a report can be filtered by. `fields` is a list's field tree, so the shared filter drawer takes it as it is: it holds
 *  everything the registry offers for the report's population except what the report excludes (all dates, or named fields).
 *  `defaults` are the conditions the report opens with, which may be none. */
export type ReportFilters = { enabled: false } | { enabled: true; fields: FieldTree; defaults: Condition[] };

/** `GET /api/reports/{key}/choices/{field}`: what to pick from when filtering by a field of a report, drawn from the accounts the
 *  person may see. The same shape a list's choices have. */
export type ReportChoices = Choices;

/** What a drill target points at. The page maps it to a route. */
export type ReportLink =
  | { to: "account"; id: number }
  | { to: "balance"; id: number }
  | { to: "list"; list: string; filters: { field: string; operator: string; value?: unknown }[] };

export type SummaryItem =
  | { key: string; label: string; kind: "money"; value: number; currency?: string; note?: string }
  | { key: string; label: string; kind: "count"; value: number; note?: string }
  | { key: string; label: string; kind: "date" | "text"; value: string; note?: string };

export type SummaryData = { items: SummaryItem[] };

export type SeriesData = {
  series: { key: string; label: string; kind: "money" | "count"; points: { x: string; value: number }[] }[];
};

/** `value` is signed financial value and adds up: a parent equals the sum of its children. `size` is separate, non-negative and
 *  present only in a sized section: a leaf's is the report's, a parent's is the sum of its leaves', added by the server. */
export type HierarchyNode = {
  id: string;
  label: string;
  value: number;
  size?: number;
  link?: ReportLink;
  /** One short line the report writes (a balance date, say), shown beside the node. */
  note?: string;
  /** The entity the colour comes from (an account names its type), turned into a slot by `slotFor`. Without one a node takes its parent's. */
  colour?: { kind: string; id: number };
  children?: HierarchyNode[];
};

export type HierarchyData = { nodes: HierarchyNode[] };

export type ColumnKind = "text" | "money" | "native_money" | "date" | "count";
export type RowCell = string | number | { minor: number; currency: string } | null;

export type RowsData = {
  columns: { key: string; label: string; kind: ColumnKind }[];
  rows: { id: string; cells: Record<string, RowCell>; link?: ReportLink }[];
};

/** Which payload each kind of section carries. A renderer for a kind takes `SectionPayload<kind>`, so no renderer narrows an untagged
 *  union: the definition says what kind a section is, and this says what its data is. */
export type SectionPayloads = { summary: SummaryData; series: SeriesData; hierarchy: HierarchyData; rows: RowsData };
export type SectionPayload<K extends SectionKind> = SectionPayloads[K];
export type SectionData = SectionPayloads[SectionKind];

export type ReportNote = { code: string; text: string; section?: string };

/** `POST /api/reports/{key}` with `{ parameters, filters }`. Every section is the one the report declared, checked. */
export type ReportResult = {
  report: string;
  today: string;
  parameters: Record<string, string | number>;
  filters: Condition[]; // the conditions that were applied: the request's, or the report's own when it named none
  currency: { code: string; minor_units: number };
  sections: Record<string, SectionData>;
  notes: ReportNote[];
};

/** What a failed request says. Classify by `code`, never by the status alone or the words of `detail`. */
export type ReportError =
  | { code: "invalid_input"; detail: string; path: (string | number)[] } // a number is a place in a list: ["filters", 0, "field"]
  | { code: "unavailable_data"; detail: string; reason: "missing_rates" | "no_system_currency"; missing_rates?: string[] }
  | { code: "calculation_error"; detail: string };

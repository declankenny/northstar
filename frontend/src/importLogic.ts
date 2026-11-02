import type { ImportColumn, ImportMapping, ImportOutcome, ImportRead } from "./api";

// What each column of the file is used as. The page keeps one choice per column and turns it into the mapping the server
// takes (a column for each target), so a column can only have one use, and a use can only be on one column.

export const TARGETS = ["date", "balance", "note", "currency"] as const;
export type Target = (typeof TARGETS)[number];
export type Use = Target | "ignore";

export const USE_LABEL: Record<Use, string> = { ignore: "Ignore", date: "Date", balance: "Balance", note: "Note", currency: "Currency" };

/** One use per column, from the mapping the server suggested. */
export function usesFrom(mapping: ImportMapping, columns: number): Use[] {
  const uses: Use[] = Array.from({ length: columns }, () => "ignore");
  for (const target of TARGETS) {
    const column = mapping[target];
    if (column !== null && column >= 0 && column < columns) uses[column] = target;
  }
  return uses;
}

export function mappingFrom(uses: Use[]): ImportMapping {
  const at = (target: Target) => {
    const column = uses.indexOf(target);
    return column === -1 ? null : column;
  };
  return { date: at("date"), balance: at("balance"), note: at("note"), currency: at("currency") };
}

/** Use a column as something. That thing can only be on one column, so it moves from wherever it was, which goes back to Ignore. */
export function setUse(uses: Use[], column: number, use: Use): Use[] {
  return uses.map((current, index) => (index === column ? use : use !== "ignore" && current === use ? "ignore" : current));
}

/** The one format the column's values fit, which is then chosen for the person, or null when it is not settled. */
export function decidedFormat(column: ImportColumn | undefined): string | null {
  return column !== undefined && column.date_formats.length === 1 ? column.date_formats[0] : null;
}

/** What the date format can be chosen from: the formats every value fits, or all of them when none does (the review then lists
 *  the values that are wrong). */
export function formatChoices(column: ImportColumn | undefined, all: string[]): string[] {
  return column !== undefined && column.date_formats.length > 0 ? column.date_formats : all;
}

export type Readiness = { ready: boolean; reason: string | null };

/** Whether the mapping can go on to the review, and if not, why, in words for the person. */
export function readiness(uses: Use[], read: ImportRead, dateFormat: string | null): Readiness {
  const date = uses.indexOf("date");
  if (date === -1) return { ready: false, reason: "Choose which column holds the date." };
  if (!uses.includes("balance")) return { ready: false, reason: "Choose which column holds the balance." };
  if (read.columns[date].date_formats.length > 1 && dateFormat === null) {
    return { ready: false, reason: "Choose the date format to continue." };
  }
  return { ready: true, reason: null };
}

/** How many balances an import would write: the ones it adds and the ones it replaces. */
export function writeCount(counts: Record<ImportOutcome, number>): number {
  return counts.add + counts.replace;
}

export const plural = (n: number, word: string) => `${n.toLocaleString("en-US")} ${word}${n === 1 ? "" : "s"}`;

/** "6 balances will be added and 2 replaced", or why nothing will be written. */
export function writeSummary(counts: Record<ImportOutcome, number>): string {
  const { add, replace } = counts;
  if (add === 0 && replace === 0) return "Nothing will be written: every date is already in the account the same, or is being skipped.";
  if (replace === 0) return `${plural(add, "balance")} will be added`;
  if (add === 0) return `${plural(replace, "balance")} will be replaced`;
  return `${plural(add, "balance")} will be added and ${replace.toLocaleString("en-US")} replaced`;
}

/** What is not listed on the review: "250 more to add, 3 more to skip". */
export function hiddenSummary(hidden: Partial<Record<ImportOutcome, number>>): string {
  const words: Record<string, string> = { add: "to add", replace: "to replace", skip: "to skip" };
  return (Object.keys(words) as ImportOutcome[])
    .filter((outcome) => (hidden[outcome] ?? 0) > 0)
    .map((outcome) => `${(hidden[outcome] as number).toLocaleString("en-US")} more ${words[outcome]}`)
    .join(", ");
}

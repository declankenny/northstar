import type { UpdateRow } from "./api";
import { centsToInput, parseCents } from "./money";

// What the Update balances screen decides about a row from its text box. Display only: the server
// checks and saves every amount, and the frontend holds no net worth rule.

/** The text a row starts with for the date shown: what is saved on it, or nothing. */
export function baselineText(row: UpdateRow): string {
  return row.existing_cents === null ? "" : centsToInput(row.existing_cents);
}

/** Whether the box differs from what is saved on the date, so it is the user's own typing. */
export function isTyped(row: UpdateRow, text: string): boolean {
  return text !== baselineText(row);
}

/** What a save sends: only the rows the person changed, and not blank (a blank row is skipped). Rows that
 *  were just prefilled from what is already saved are left out, so saving one row can never write back
 *  another row's stale value over someone else's change. The text is sent as typed: the server checks it. */
export function changedAmounts(rows: UpdateRow[], values: Record<number, string>): Record<number, string> {
  const amounts: Record<number, string> = {};
  for (const row of rows) {
    const text = values[row.id] ?? "";
    if (isTyped(row, text) && text.trim() !== "") amounts[row.id] = text;
  }
  return amounts;
}

export type RowState =
  | { kind: "blank" }
  | { kind: "invalid" }
  | { kind: "new"; cents: number }       // nothing saved on this date yet
  | { kind: "replace"; cents: number }   // differs from what is saved on this date
  | { kind: "same"; cents: number };     // equals what is saved on this date

export function rowState(row: UpdateRow, text: string): RowState {
  if (text.trim() === "") return { kind: "blank" };
  const cents = parseCents(text);
  if (cents === null) return { kind: "invalid" };
  if (row.existing_cents === null) return { kind: "new", cents };
  return { kind: cents === row.existing_cents ? "same" : "replace", cents };
}

/** The new balance minus the last one, and whether that is good news (assets up, liabilities down). */
export function changeFromLast(row: UpdateRow, cents: number): { diff: number; good: boolean } | null {
  if (row.last_cents === null) return null;
  const diff = cents - row.last_cents;
  return { diff, good: row.class_name === "Asset" ? diff >= 0 : diff <= 0 };
}

export type Summary = { entered: number; added: number; replacing: number; same: number; invalid: number };

export function summarize(rows: UpdateRow[], values: Record<number, string>): Summary {
  const summary: Summary = { entered: 0, added: 0, replacing: 0, same: 0, invalid: 0 };
  for (const row of rows) {
    const state = rowState(row, values[row.id] ?? "");
    if (state.kind === "blank") continue;
    summary.entered += 1;
    if (state.kind === "new") summary.added += 1;
    else if (state.kind === "replace") summary.replacing += 1;
    else if (state.kind === "same") summary.same += 1;
    else summary.invalid += 1;
  }
  return summary;
}

/** The form after moving to another date. Rows the user typed in keep their text when `keep` is set,
 *  and every other row shows what the new date has saved. Nothing is written either way. */
export function valuesForDate(
  oldRows: UpdateRow[], oldValues: Record<number, string>, newRows: UpdateRow[], keep: boolean,
): Record<number, string> {
  const oldById = new Map(oldRows.map((row) => [row.id, row]));
  const next: Record<number, string> = {};
  for (const row of newRows) {
    const before = oldById.get(row.id);
    const text = oldValues[row.id] ?? "";
    next[row.id] = keep && before && isTyped(before, text) ? text : baselineText(row);
  }
  return next;
}

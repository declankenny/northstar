import type { Conflict } from "./api";
import { formatDate } from "./dates";
import { formatCents } from "./money";

/** "Sam Example on Nov 2, 2026": who changed a balance and when, as far as the server could tell. */
function whoWhen(conflict: Conflict): string {
  const who = conflict.by ?? "someone";
  return conflict.on === null ? who : `${who} on ${formatDate(conflict.on)}`;
}

/** What happened to a balance, for a dialog: "Demo Savings on Mar 31, 2026 was changed by Sam Example on Nov 2, 2026. It is now
 *  $1,200.00 (you opened it at $1,000.00)." `openedAt` is the amount the person was looking at, which only the page knows. */
export function conflictText(conflict: Conflict, openedAt?: number): string {
  const where = `${conflict.account_name} on ${conflict.date === null ? "that date" : formatDate(conflict.date)}`;
  if (conflict.kind === "deleted") return `The balance for ${where} was deleted by ${whoWhen(conflict)}.`;
  const now = conflict.amount_cents === null ? "" : ` It is now ${formatCents(conflict.amount_cents)}${
    openedAt === undefined ? "" : ` (you opened it at ${formatCents(openedAt)})`}.`;
  return `${where} was ${conflict.kind === "added" ? "added" : "changed"} by ${whoWhen(conflict)}.${now}`;
}

/** The short note under a row of the Update screen: "Changed by Sam Example on Nov 2, 2026: now $1,200.00". */
export function rowConflictNote(conflict: Conflict): string {
  const verb = { changed: "Changed", added: "Added", deleted: "Deleted" }[conflict.kind];
  const now = conflict.amount_cents === null ? "" : `: now ${formatCents(conflict.amount_cents)}`;
  return `${verb} by ${whoWhen(conflict)}${now}`;
}

/** The banner over the Update screen after a refused save. */
export function conflictBanner(count: number): string {
  return count === 1
    ? "Nothing was saved. 1 balance changed since you opened this date. Check the marked row: pressing Save again replaces it with what you typed."
    : `Nothing was saved. ${count} balances changed since you opened this date. Check the marked rows: pressing Save again replaces them with what you typed.`;
}

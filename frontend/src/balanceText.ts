import type { BalanceRow, Neighbours } from "./api";
import { formatDate } from "./dates";
import { type Currency, formatCents } from "./money";

/** What deleting one balance does to the history, in words: the balance, and the ones either side of it on the account. It is the
 *  sentence under "Delete this balance?" on the balance's page. */
export function deleteConsequence(entry: Pick<BalanceRow, "as_of_date" | "amount_cents">, { older, newer }: Neighbours, currency: Currency): string {
  const head = `The ${formatCents(entry.amount_cents, currency)} entry for ${formatDate(entry.as_of_date)} is removed. `;
  if (!older && !newer) return head + "It is the only balance, so this account will have no history.";
  if (!older) return head + `It is the first balance, so the history will start at the next entry, on ${formatDate(newer!.as_of_date)}.`;
  return head + `Until the next entry, the balance will go back to ${formatCents(older.amount_cents, currency)} (entered ${formatDate(older.as_of_date)}).`;
}

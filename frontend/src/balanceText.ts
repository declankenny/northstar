import type { BalanceRow } from "./api";
import { formatDate } from "./dates";
import { type Currency, formatCents } from "./money";

/** What deleting one balance does to the history, in words: the account's balances newest first, and the one at `index`. It is the
 *  sentence under "Delete this balance?" on the account page and on the balance's own page. */
export function deleteConsequence(balances: BalanceRow[], index: number, currency: Currency): string {
  const entry = balances[index];
  const head = `The ${formatCents(entry.amount_cents, currency)} entry for ${formatDate(entry.as_of_date)} is removed. `;
  if (balances.length === 1) return head + "It is the only balance, so this account will have no history.";
  if (index === balances.length - 1) {
    return head + `It is the first balance, so the history will start at the next entry, on ${formatDate(balances[index - 1].as_of_date)}.`;
  }
  const before = balances[index + 1];
  return head + `Until the next entry, the balance will go back to ${formatCents(before.amount_cents, currency)} (entered ${formatDate(before.as_of_date)}).`;
}

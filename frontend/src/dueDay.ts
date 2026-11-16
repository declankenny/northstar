/** An account's payment due day (#258): the words the page uses for it. The date itself is worked out by the server. */

import { dayNumber } from "./dates";

/** 1 becomes "1st", 12 "12th", 23 "23rd". */
export function ordinal(n: number): string {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  const suffix = teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

/** What the page says about the due day: when in the month, and that paying is not tracked. A day a short month lacks says what happens. */
export function dueDayText(day: number): string {
  const when = `The ${ordinal(day)} of each month${day > 28 ? ", or the last day of a shorter month" : ""}.`;
  return `${when} Payments aren't tracked.`;
}

/** How far away the next due date is, from the server's own today: "Due today", "Due tomorrow" or "in 3 days". */
export function dueIn(today: string, nextDue: string): string {
  const days = dayNumber(nextDue) - dayNumber(today);
  if (days <= 0) return "Due today";
  return days === 1 ? "Due tomorrow" : `in ${days} days`;
}

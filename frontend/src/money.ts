// Money is integer cents everywhere. It is only turned into dollars here, for display, with
// whole-number arithmetic, so no floating point touches an amount.

/** 123456 becomes "$1,234.56" and -5 becomes "-$0.05". */
export function formatCents(cents: number): string {
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  const rest = String(abs % 100).padStart(2, "0");
  return `${cents < 0 ? "-" : ""}$${dollars}.${rest}`;
}

// About $100 billion, in cents: the same limit as the server's, so a typo is caught the same way.
const MAX_CENTS = 99_999_999_999_99;
const AMOUNT = /^(\d{1,3}(?:,\d{3})+|\d+)?(?:\.(\d{1,2}))?$/;

/** Typed text such as "1,234.56", "$25" or "-$25.00" as integer cents, or null when the server would
 *  refuse it. This mirrors the server's parse_cents so the page can show a change as you type; the
 *  server still checks every amount when it is saved. */
export function parseCents(text: string): number | null {
  let s = text.trim().replace(/ /g, "");
  const negative = s.startsWith("-");
  if (negative) s = s.slice(1);
  if (s.startsWith("$")) s = s.slice(1);
  const match = AMOUNT.exec(s);
  if (!s || !match || (match[1] === undefined && match[2] === undefined)) return null;
  const cents = Number((match[1] ?? "0").replace(/,/g, "")) * 100 + Number((match[2] ?? "0").padEnd(2, "0"));
  if (cents > MAX_CENTS) return null;
  return negative && cents !== 0 ? -cents : cents;
}

/** The change as a percent of where it started, or null when there is no sensible base (zero). */
export function percentChange(diff: number, base: number): number | null {
  return base === 0 ? null : (diff / Math.abs(base)) * 100;
}

/** 123456 becomes "1234.56", the plain text an amount box starts with (no symbol or commas to strip). */
export function centsToInput(cents: number): string {
  const abs = Math.abs(cents);
  return `${cents < 0 ? "-" : ""}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

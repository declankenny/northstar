// Money is integer cents everywhere. It is only turned into dollars here, for display, with
// whole-number arithmetic, so no floating point touches an amount.

/** 123456 becomes "$1,234.56" and -5 becomes "-$0.05". */
export function formatCents(cents: number): string {
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  const rest = String(abs % 100).padStart(2, "0");
  return `${cents < 0 ? "-" : ""}$${dollars}.${rest}`;
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

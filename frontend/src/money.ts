// Money is an integer count of the currency's minor unit everywhere (cents for US dollars, whole yen, fils for Kuwaiti
// dinars). It is only turned into a decimal here, for display, with whole-number arithmetic, so no floating point touches an
// amount.
//
// Until accounts can be in different currencies, every amount is in the system currency, which the app tells this module
// once it knows it (setCurrency). Locale-aware symbols and separators come later; for now US dollars show as $1,234.56 and
// any other currency as its code, such as JPY 1,234.

export type Currency = { code: string; name: string; minor_units: number };

const DOLLARS: Currency = { code: "USD", name: "US Dollar", minor_units: 2 };
let current: Currency = DOLLARS;

/** Tell the module which currency amounts are in. Null (the system currency is not set yet) leaves dollars. */
export function setCurrency(currency: Currency | null): void {
  current = currency ?? DOLLARS;
}

export function getCurrency(): Currency {
  return current;
}

/** 123456 becomes "$1,234.56" and -5 becomes "-$0.05" in dollars; 1234 yen becomes "JPY 1,234". */
export function formatCents(cents: number): string {
  const abs = Math.abs(cents);
  const scale = 10 ** current.minor_units;
  const whole = Math.floor(abs / scale).toLocaleString("en-US");
  const rest = current.minor_units === 0 ? "" : `.${String(abs % scale).padStart(current.minor_units, "0")}`;
  const symbol = current.code === "USD" ? "$" : `${current.code} `;
  return `${cents < 0 ? "-" : ""}${symbol}${whole}${rest}`;
}

// About 10^13 minor units, whatever the currency: the same limit as the server's, so a typo is caught the same way.
const MAX_CENTS = 99_999_999_999_99;

/** Typed text such as "1,234.56", "$25" or "-25.00" as an integer count of minor units, or null when the server would
 *  refuse it (more decimal places than the currency has, for one). This mirrors the server's parse_amount so the page can
 *  show a change as you type; the server still checks every amount when it is saved. */
export function parseCents(text: string): number | null {
  const places = current.minor_units;
  let s = text.trim().replace(/ /g, "");
  const negative = s.startsWith("-");
  if (negative) s = s.slice(1);
  if (current.code === "USD" && s.startsWith("$")) s = s.slice(1);
  const match = new RegExp(`^(\\d{1,3}(?:,\\d{3})+|\\d+)?(?:\\.(\\d{1,${Math.max(places, 1)}}))?$`).exec(s);
  if (!s || !match || (match[1] === undefined && match[2] === undefined)) return null;
  if (places === 0 && match[2] !== undefined) return null;
  const amount = Number((match[1] ?? "0").replace(/,/g, "")) * 10 ** places + Number((match[2] ?? "0").padEnd(places, "0"));
  if (amount > MAX_CENTS) return null;
  return negative && amount !== 0 ? -amount : amount;
}

/** The change as a percent of where it started, or null when there is no sensible base (zero). */
export function percentChange(diff: number, base: number): number | null {
  return base === 0 ? null : (diff / Math.abs(base)) * 100;
}

/** 123456 becomes "1234.56", the plain text an amount box starts with (no symbol or commas to strip). */
export function centsToInput(cents: number): string {
  const abs = Math.abs(cents);
  const scale = 10 ** current.minor_units;
  const rest = current.minor_units === 0 ? "" : `.${String(abs % scale).padStart(current.minor_units, "0")}`;
  return `${cents < 0 ? "-" : ""}${Math.floor(abs / scale)}${rest}`;
}

/** What an empty amount box shows: 0.00 for dollars, 0 for yen, 0.000 for dinars. */
export function amountPlaceholder(): string {
  return current.minor_units === 0 ? "0" : `0.${"0".repeat(current.minor_units)}`;
}

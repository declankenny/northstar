// Money is an integer count of the currency's minor unit everywhere (cents for US dollars, whole yen, fils for Kuwaiti
// dinars). It is only turned into a decimal here, for display, with whole-number arithmetic, so no floating point touches an
// amount.
//
// Until accounts can be in different currencies, every amount is in the system currency, which the app tells this module
// once it knows it (setCurrency). Marks, grouping and where the currency goes come from the person's locale (locale.ts).
// US dollars show as $1,234.56 in US English and every other case shows the currency code.

import { formatInteger, getLocale, normalizeGroupMarks } from "./locale";

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

const decimals = (abs: number, places: number) =>
  places === 0 ? "" : getLocale().decimal_mark + String(abs % 10 ** places).padStart(places, "0");

/** 123456 becomes "$1,234.56" for US dollars in US English, "EUR 1,234.56" otherwise, and "1.234,56 EUR" where the locale puts
 *  the currency after the number. A negative amount has its minus at the very start. */
export function formatCents(cents: number): string {
  const locale = getLocale();
  const abs = Math.abs(cents);
  const number = formatInteger(Math.floor(abs / 10 ** current.minor_units)) + decimals(abs, current.minor_units);
  const minus = cents < 0 ? "-" : "";
  if (current.code === "USD" && locale.tag === "en-US") return `${minus}$${number}`;
  const spacing = locale.currency_code_spacing;
  return minus + (locale.currency_position === "prefix" ? `${current.code}${spacing}${number}` : `${number}${spacing}${current.code}`);
}

// About 10^13 minor units, whatever the currency: the same limit as the server's, so a typo is caught the same way.
const MAX_CENTS = 99_999_999_999_99;

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Typed text such as "1,234.56", "$25" or "-25.00" as an integer count of minor units, or null when the server would
 *  refuse it. It is read in the person's locale: their decimal mark and group mark and nothing else, and the look-alikes of the
 *  group mark. More decimal places than the currency has is refused. This mirrors the server's parse_amount so the page can
 *  show a change as you type; the server still checks every amount when it is saved. */
export function parseCents(text: string): number | null {
  const places = current.minor_units;
  const { decimal_mark: decimal, group_mark: group } = getLocale();
  let s = text.trim();
  const negative = s.startsWith("-");
  if (negative) s = s.slice(1);
  if (current.code === "USD" && s.startsWith("$")) s = s.slice(1);
  s = normalizeGroupMarks(s, group);
  const at = s.indexOf(decimal);
  const whole = at < 0 ? s : s.slice(0, at);
  const fraction = at < 0 ? "" : s.slice(at + decimal.length);
  const wholeOk = whole === "" || new RegExp(`^(?:\\d{1,3}(?:${escape(group)}\\d{3})+|\\d+)$`).test(whole);
  const fractionOk = at < 0 || (places > 0 && fraction.length >= 1 && fraction.length <= places && /^[0-9]+$/.test(fraction));
  if (!s || !wholeOk || !fractionOk) return null;
  const amount = Number(whole.split(group).join("") || "0") * 10 ** places + Number(fraction.padEnd(places, "0") || "0");
  if (amount > MAX_CENTS) return null;
  return negative && amount !== 0 ? -amount : amount;
}

/** The change as a percent of where it started, or null when there is no sensible base (zero). */
export function percentChange(diff: number, base: number): number | null {
  return base === 0 ? null : (diff / Math.abs(base)) * 100;
}

/** 123456 becomes "1234.56", or "1234,56" where the decimal mark is a comma: the text an amount box starts with, with no
 *  grouping or currency, so what is edited is exactly what the parser reads. */
export function centsToInput(cents: number): string {
  const abs = Math.abs(cents);
  return `${cents < 0 ? "-" : ""}${Math.floor(abs / 10 ** current.minor_units)}${decimals(abs, current.minor_units)}`;
}

/** What an empty amount box shows: 0.00 for dollars, 0 for yen, 0,00 where the decimal mark is a comma. */
export function amountPlaceholder(): string {
  const { decimal_mark } = getLocale();
  return current.minor_units === 0 ? "0" : `0${decimal_mark}${"0".repeat(current.minor_units)}`;
}

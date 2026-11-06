// Money is an integer count of the currency's minor unit everywhere (cents for US dollars, whole yen, fils for Kuwaiti
// dinars). It is only turned into a decimal here, for display, with whole-number arithmetic, so no floating point touches an
// amount.
//
// An amount is in the currency of its account, which a caller passes. When it does not, the amount is in the system currency,
// which the app tells this module once it knows it (setCurrency): totals, and the pages that have no account. Marks, grouping and
// where the currency goes come from the person's locale (locale.ts).
// US dollars show as $1,234.56 in US English and every other case shows the currency code.

import { formatInteger, getLocale, type Locale, normalizeGroupMarks } from "./locale";

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

const decimals = (abs: number, places: number, locale: Locale = getLocale()) =>
  places === 0 ? "" : locale.decimal_mark + String(abs % 10 ** places).padStart(places, "0");

/** The mark shown beside an amount box: $ for US dollars in US English, the currency code otherwise. */
export function currencyMark(currency: Currency = current): string {
  return currency.code === "USD" && getLocale().tag === "en-US" ? "$" : currency.code;
}

/** 123456 becomes "$1,234.56" for US dollars in US English, "EUR 1,234.56" otherwise, and "1.234,56 EUR" where the locale puts
 *  the currency after the number. A negative amount has its minus at the very start. */
export function formatCents(cents: number, currency: Currency = current): string {
  const locale = getLocale();
  const abs = Math.abs(cents);
  const number = formatInteger(Math.floor(abs / 10 ** currency.minor_units)) + decimals(abs, currency.minor_units);
  const minus = cents < 0 ? "-" : "";
  if (currency.code === "USD" && locale.tag === "en-US") return `${minus}$${number}`;
  const spacing = locale.currency_code_spacing;
  return minus + (locale.currency_position === "prefix" ? `${currency.code}${spacing}${number}` : `${number}${spacing}${currency.code}`);
}

/** An exchange rate as the server stores it ("1234.5000": digits and a point) the way the person reads numbers: the whole part
 *  grouped from four digits with the locale's group mark, and the locale's decimal mark. The digits after the point stay as they are. */
export function formatRate(rate: string): string {
  const [whole, fraction] = rate.split(".");
  return formatInteger(Number(whole)) + (fraction === undefined ? "" : getLocale().decimal_mark + fraction);
}

// About 10^13 minor units, whatever the currency: the same limit as the server's, so a typo is caught the same way.
const MAX_CENTS = 99_999_999_999_99;

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** What typed text means: an amount in minor units, or why it cannot be read. */
export type Reading = { cents: number } | { message: string };

/** Read typed text such as "1,234.56", "$25" or "-25.00" in the person's locale: their decimal mark and group mark and nothing
 *  else, and the look-alikes of the group mark. More decimal places than the currency has is refused. Null when nothing is
 *  typed. The refusals are worded as the server's are, so the page can say why as you type. This mirrors the server's
 *  parse_amount; the server still checks every amount when it is saved. */
export function readAmount(text: string, currency: Currency = current): Reading | null {
  if (text.trim() === "") return null;
  const places = currency.minor_units;
  const { decimal_mark: decimal, group_mark: group } = getLocale();
  let s = text.trim();
  const negative = s.startsWith("-");
  if (negative) s = s.slice(1);
  if (currency.code === "USD" && s.startsWith("$")) s = s.slice(1);
  s = normalizeGroupMarks(s, group);
  const at = s.indexOf(decimal);
  const whole = at < 0 ? s : s.slice(0, at);
  const fraction = at < 0 ? "" : s.slice(at + decimal.length);
  const wholeOk = whole === "" || new RegExp(`^(?:\\d{1,3}(?:${escape(group)}\\d{3})+|\\d+)$`).test(whole);
  const fractionOk = at < 0 || (places > 0 && fraction.length >= 1 && fraction.length <= places && /^[0-9]+$/.test(fraction));
  if (!s || !wholeOk || !fractionOk) {
    if (places === 0) return { message: "Enter a whole amount like 1234 or -25. This currency has no decimal places." };
    const example = `Enter an amount like 1234${decimal}${"5678".slice(0, places)} or -25${decimal}${"0".repeat(places)}.`;
    const other = decimal === "." ? "," : ".";
    return { message: !wholeOk && whole.includes(other) ? `Use ${decimal} for decimals. ${example}` : example };
  }
  const amount = Number(whole.split(group).join("") || "0") * 10 ** places + Number(fraction.padEnd(places, "0") || "0");
  if (amount > MAX_CENTS) return { message: "That amount is too large." };
  return { cents: negative && amount !== 0 ? -amount : amount };
}

/** Typed text as an integer count of minor units, or null when the server would refuse it (or nothing is typed). */
export function parseCents(text: string, currency: Currency = current): number | null {
  const reading = readAmount(text, currency);
  return reading && "cents" in reading ? reading.cents : null;
}

/** The change as a percent of where it started, or null when there is no sensible base (zero). */
export function percentChange(diff: number, base: number): number | null {
  return base === 0 ? null : (diff / Math.abs(base)) * 100;
}

/** 123456 becomes "1234.56", or "1234,56" where the decimal mark is a comma: the text an amount box starts with, with no
 *  grouping or currency, so what is edited is exactly what the parser reads. `locale` is for a caller that needs the text as
 *  it was written under another locale. */
export function centsToInput(cents: number, locale: Locale = getLocale(), currency: Currency = current): string {
  const abs = Math.abs(cents);
  return `${cents < 0 ? "-" : ""}${Math.floor(abs / 10 ** currency.minor_units)}${decimals(abs, currency.minor_units, locale)}`;
}

/** What an empty amount box shows: 0.00 for dollars, 0 for yen, 0,00 where the decimal mark is a comma. */
export function amountPlaceholder(currency: Currency = current): string {
  const { decimal_mark } = getLocale();
  return currency.minor_units === 0 ? "0" : `0${decimal_mark}${"0".repeat(currency.minor_units)}`;
}

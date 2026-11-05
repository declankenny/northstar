// A person's locale: how numbers and dates are shown and typed. The conventions are rows of the server's ref_locales table,
// which /api/me hands over, so the page and the server read the same data and cannot disagree. Nothing here uses the browser's
// Intl, whose output differs between browsers. See docs/design/locale.md.
//
// Three rules are not part of the data: groups of three digits, grouping from four digits and an ASCII minus.

export type Locale = {
  tag: string;
  label: string;
  decimal_mark: string;
  group_mark: string;
  date_template: string; // {year} {month} {month2} {month_short} {day} {day2} and literal text
  currency_position: "prefix" | "suffix";
  currency_code_spacing: string; // the exact text between a currency code and the number
};

/** US English: what a person has before they choose, and what the page shows until the server has said. */
export const US_ENGLISH: Locale = {
  tag: "en-US",
  label: "English (United States)",
  decimal_mark: ".",
  group_mark: ",",
  date_template: "{month_short} {day}, {year}",
  currency_position: "prefix",
  currency_code_spacing: "\u00a0",
};

let current: Locale = US_ENGLISH;

/** Tell the page which locale to use. Null leaves US English. */
export function setLocale(locale: Locale | null): void {
  current = locale ?? US_ENGLISH;
}

export function getLocale(): Locale {
  return current;
}

/** Marks that look alike and are read as the same group mark when typed. A group mark in one of these sets also takes the others
 *  of its set, and nothing else. */
const GROUP_ALIASES = [new Set([" ", "\u00a0", "\u202f"]), new Set(["'", "\u2019", "\u02bc"])];

/** Typed text with the look-alikes of the locale's group mark made into that mark. */
export function normalizeGroupMarks(text: string, group: string): string {
  const aliases = GROUP_ALIASES.find((set) => set.has(group));
  return aliases ? [...text].map((c) => (aliases.has(c) ? group : c)).join("") : text;
}

/** 1234567 becomes "1,234,567" (or "1.234.567" and so on): grouped from four digits, with the locale's group mark. */
export function formatInteger(n: number): string {
  const digits = String(Math.abs(Math.trunc(n)));
  const { group_mark } = current;
  let out = digits;
  if (digits.length > 3) {
    const groups: string[] = [];
    for (let end = digits.length; end > 0; end -= 3) groups.unshift(digits.slice(Math.max(0, end - 3), end));
    out = groups.join(group_mark);
  }
  return `${n < 0 ? "-" : ""}${out}`;
}

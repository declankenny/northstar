// The same hand-written vectors the server's tests read (frontend/src/testdata/locale_vectors.json), so the page and the server are held to
// one set of expected results. They are not generated, so a mistake in the table cannot copy itself into the tests.
import { afterEach, describe, expect, it } from "vitest";
import vectors from "./testdata/locale_vectors.json";
import { formatDate } from "./dates";
import { formatInteger, getLocale, type Locale, setLocale, US_ENGLISH } from "./locale";
import { amountPlaceholder, centsToInput, formatCents, parseCents, setCurrency } from "./money";

type Conventions = Omit<Locale, "tag" | "label">;
const conventions = vectors.locales as Record<string, Conventions>;

const locale = (tag: string): Locale => ({ tag, label: tag, ...conventions[tag] } as Locale);
const use = (tag: string, code = "EUR", units = 2) => {
  setLocale(locale(tag));
  setCurrency({ code, name: code, minor_units: units });
};

afterEach(() => {
  setLocale(null);
  setCurrency(null);
});

describe("US English is the fallback", () => {
  it("is what the vectors say for en-US", () => {
    expect({ ...US_ENGLISH, tag: undefined, label: undefined }).toEqual({ ...locale("en-US"), tag: undefined, label: undefined });
    expect(getLocale().tag).toBe("en-US");
  });
});

describe("parsing in each locale", () => {
  it.each(vectors.parse_ok)("reads $locale $units places $text", (v) => {
    use(v.locale, "EUR", v.units);
    expect(parseCents(v.text)).toBe(v.minor);
  });

  it.each(vectors.parse_dollar_ok)("reads a dollar sign for US dollars: $locale $text", (v) => {
    use(v.locale, "USD", v.units);
    expect(parseCents(v.text)).toBe(v.minor);
  });

  it("does not read a dollar sign for another currency", () => {
    use("en-US", "EUR", 2);
    expect(parseCents("$25")).toBeNull();
  });

  it.each(vectors.parse_refused)("refuses $locale $units places $text", (v) => {
    use(v.locale, "EUR", v.units);
    expect(parseCents(v.text)).toBeNull();
  });
});

describe("formatting an amount", () => {
  it.each(vectors.format_amount)("shows $locale $code $minor as $text", (v) => {
    use(v.locale, v.code, v.units);
    expect(formatCents(v.minor)).toBe(v.text);
  });
});

describe("editable text", () => {
  it.each(vectors.format_editable)("starts $locale $units places $minor as $text", (v) => {
    use(v.locale, "EUR", v.units);
    expect(centsToInput(v.minor)).toBe(v.text);
  });

  it.each(vectors.format_editable)("reads back what it wrote: $locale $text", (v) => {
    use(v.locale, "EUR", v.units);
    expect(parseCents(centsToInput(v.minor))).toBe(v.minor);
  });

  it("round-trips every amount in a range, in every locale and precision", () => {
    for (const tag of Object.keys(conventions)) {
      for (const units of [0, 2, 3]) {
        use(tag, "EUR", units);
        for (const minor of [0, 1, 5, 99, 100, 999, 1000, 123456, -1, -99, -123456, 9_999_999_999_999, -9_999_999_999_999]) {
          expect(parseCents(centsToInput(minor)), `${tag} ${units} ${minor}`).toBe(minor);
        }
      }
    }
  });

  it("shows the empty box with the locale's own mark", () => {
    use("en-US", "EUR", 2);
    expect(amountPlaceholder()).toBe("0.00");
    use("de-DE", "EUR", 2);
    expect(amountPlaceholder()).toBe("0,00");
    use("de-DE", "JPY", 0);
    expect(amountPlaceholder()).toBe("0");
  });
});

describe("dates and counts", () => {
  it.each(vectors.format_date)("shows $locale $iso as $text", (v) => {
    setLocale(locale(v.locale));
    expect(formatDate(v.iso)).toBe(v.text);
  });

  it.each(vectors.format_integer)("shows $locale $n as $text", (v) => {
    setLocale(locale(v.locale));
    expect(formatInteger(v.n)).toBe(v.text);
  });

  it("groups a negative count too", () => {
    expect(formatInteger(-1234567)).toBe("-1,234,567");
  });
});

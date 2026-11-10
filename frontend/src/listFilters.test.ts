import { afterEach, describe, expect, it } from "vitest";
import type { Choices, FieldNode, FieldTree } from "./api";
import { describe as say, flatten, isSingleChoice, problem, readNumber, sameConditions, startCondition, toWire, withOperator } from "./listFilters";
import { setLocale, US_ENGLISH } from "./locale";

const LABELS: Record<string, string> = { is_any_of: "is one of", is_not_any_of: "is not one of", is_not: "is not", is: "is" };   // as the server words them
const ops = (...names: string[]) => names.map((name) => ({ name, label: LABELS[name] ?? name.replaceAll("_", " ") }));
const NUMBER_OPS = ops("equals", "at_least", "at_most", "between", "is_empty");
const node = (over: Partial<FieldNode>): FieldNode => ({
  key: "k", label: "K", path_label: "K", kind: "text", scale: null, operators: ops("contains", "equals", "is_empty", "is_not_empty"), choices: null, ...over,
});
const TEXT = node({ key: "note", label: "Note", path_label: "Note" });
const WHOLE = node({ key: "count", kind: "integer", operators: NUMBER_OPS });
const HUNDREDTHS = node({ key: "degrees", kind: "decimal", scale: 2, operators: NUMBER_OPS });
const AMOUNT = node({ key: "value", path_label: "Value", kind: "amount", operators: NUMBER_OPS });
const DAY = node({ key: "as_of_date", path_label: "Date", kind: "date", operators: ops("before", "after", "between", "is_empty") });
const FLAG = node({ key: "stale", path_label: "Stale", kind: "yes_no", operators: ops("is_yes", "is_no") });
const STATUS = node({ key: "status", path_label: "Status", kind: "choice", operators: ops("is_any_of"), choices: "values", values: ["Open", "Closed"] });
const ACCOUNT = node({ key: "account", path_label: "Account", kind: "choice", operators: ops("is_any_of"), choices: "records" });

afterEach(() => setLocale(null));

describe("the columns a list offers, flat", () => {
  it("lists the fields, the relations and everything under a relation, in the order they are shown", () => {
    const deep = node({ key: "account.currency.code", path_label: "Account › Currency › Code" });
    const currency = node({ key: "account.currency", path_label: "Account › Currency", choices: "records", children: { fields: [deep], relations: [] } });
    const account = node({ key: "account", choices: "records", children: { fields: [], relations: [currency] } });
    const tree: FieldTree = { fields: [TEXT], relations: [account] };
    expect(flatten(tree).map((n) => n.key)).toEqual(["note", "account", "account.currency", "account.currency.code"]);
    expect(flatten(null)).toEqual([]);
  });
});

describe("a new condition", () => {
  it("starts on the column's first operator, with an empty value of the right shape", () => {
    expect(startCondition(TEXT)).toEqual({ field: "note", operator: "contains", value: "" });
    expect(startCondition(DAY)).toEqual({ field: "as_of_date", operator: "before", value: "" });
    expect(startCondition(STATUS)).toEqual({ field: "status", operator: "is_any_of", value: [] });
    expect(startCondition(FLAG)).toEqual({ field: "stale", operator: "is_yes" });          // no value at all
  });

  it("keeps what was typed when the new operator still fits, and starts again when it does not", () => {
    const typed = { field: "count", operator: "equals", value: "5" };
    expect(withOperator(WHOLE, typed, "at_least")).toEqual({ field: "count", operator: "at_least", value: "5" });
    expect(withOperator(WHOLE, typed, "between")).toEqual({ field: "count", operator: "between", value: ["", ""] });
    expect(withOperator(WHOLE, typed, "is_empty")).toEqual({ field: "count", operator: "is_empty" });
    expect(withOperator(WHOLE, { field: "count", operator: "is_empty" }, "equals")).toEqual({ field: "count", operator: "equals", value: "" });
    expect(withOperator(WHOLE, { field: "count", operator: "between", value: ["1", "2"] }, "equals")).toEqual({ field: "count", operator: "equals", value: "" });
  });
});

describe("reading a typed number", () => {
  it("reads whole numbers, decimals and negatives, and writes them with a point", () => {
    expect(readNumber("1234", 0)).toEqual({ number: "1234" });
    expect(readNumber(" -12.5 ", 2)).toEqual({ number: "-12.5" });
    expect(readNumber("0.125", 3)).toEqual({ number: "0.125" });
    expect(readNumber("1,234.50", 2)).toEqual({ number: "1234.50" });
  });

  it("refuses more places than the column has, never rounding", () => {
    expect(readNumber("1.5", 0)).toEqual({ message: "Type a whole number." });
    expect(readNumber("1.234", 2)).toEqual({ message: "Use at most 2 decimal places." });
    expect(readNumber("1.234", null)).toEqual({ number: "1.234" });
  });

  it("refuses what is not a number", () => {
    for (const bad of ["", "  ", "abc", "1.2.3", "1,2", "--1", "1e5", ".5", "5.", "$5", "1,23,456", "9".repeat(19)]) {
      expect(readNumber(bad, null), bad).toEqual({ message: "Type a number." });
    }
  });

  it("reads in the person's own decimal and group marks", () => {
    setLocale({ ...US_ENGLISH, tag: "de-DE", decimal_mark: ",", group_mark: "." });
    expect(readNumber("1.234,5", 2)).toEqual({ number: "1234.5" });
    expect(readNumber("1,5", 1)).toEqual({ number: "1.5" });
    expect(readNumber("1.5", 1)).toEqual({ message: "Type a number." });          // a point is a group mark here, and 5 is not a group of three
  });
});

describe("whether a condition is complete", () => {
  const bad = (n: FieldNode, c: Parameters<typeof problem>[1]) => problem(n, c);

  it("needs text for a text condition, and nothing for is empty", () => {
    expect(bad(TEXT, { field: "note", operator: "contains", value: "" })).toBe("Type the text to look for.");
    expect(bad(TEXT, { field: "note", operator: "contains", value: "  " })).toBe("Type the text to look for.");
    expect(bad(TEXT, { field: "note", operator: "contains", value: "x".repeat(257) })).toBe("That text is too long to filter by.");
    expect(bad(TEXT, { field: "note", operator: "contains", value: "x".repeat(256) })).toBeNull();
    expect(bad(TEXT, { field: "note", operator: "is_empty" })).toBeNull();
  });

  it("needs a number the column can hold, and a range that does not run backwards", () => {
    expect(bad(WHOLE, { field: "count", operator: "equals", value: "x" })).toBe("Type a number.");
    expect(bad(WHOLE, { field: "count", operator: "equals", value: "2.5" })).toBe("Type a whole number.");
    expect(bad(HUNDREDTHS, { field: "degrees", operator: "at_least", value: "1.234" })).toBe("Use at most 2 decimal places.");
    expect(bad(AMOUNT, { field: "value", operator: "at_least", value: "1.2345" })).toBe("Use at most 3 decimal places.");
    expect(bad(AMOUNT, { field: "value", operator: "between", value: ["1", ""] })).toBe("Type a number.");
    expect(bad(AMOUNT, { field: "value", operator: "between", value: ["5", "1"] })).toBe("The range ends before it starts.");
    expect(bad(AMOUNT, { field: "value", operator: "between", value: ["1", "1"] })).toBeNull();            // both ends are included
    expect(bad(AMOUNT, { field: "value", operator: "between", value: ["-5", "10"] })).toBeNull();
    expect(bad(AMOUNT, { field: "value", operator: "between", value: ["9", "10.5"] })).toBeNull();          // numbers, not text, are compared
    expect(bad(AMOUNT, { field: "value", operator: "is_empty" })).toBeNull();
  });

  it("needs a real date, and a range that does not run backwards", () => {
    expect(bad(DAY, { field: "as_of_date", operator: "after", value: "" })).toBe("Choose a real date.");
    expect(bad(DAY, { field: "as_of_date", operator: "after", value: "2026-02-30" })).toBe("Choose a real date.");
    expect(bad(DAY, { field: "as_of_date", operator: "after", value: "2026-2-3" })).toBe("Choose a real date.");
    expect(bad(DAY, { field: "as_of_date", operator: "after", value: "2026-02-28" })).toBeNull();
    expect(bad(DAY, { field: "as_of_date", operator: "between", value: ["2026-03-01", "2026-02-01"] })).toBe("The range ends before it starts.");
    expect(bad(DAY, { field: "as_of_date", operator: "between", value: ["2026-02-01", "2026-02-01"] })).toBeNull();
    expect(bad(DAY, { field: "as_of_date", operator: "between", value: ["2026-02-01", ""] })).toBe("Choose a real date.");
    expect(bad(DAY, { field: "as_of_date", operator: "between", value: "2026-02-01" })).toBe("Give the two ends of the range.");
  });

  it("needs at least one choice", () => {
    expect(bad(STATUS, { field: "status", operator: "is_any_of", value: [] })).toBe("Choose at least one value.");
    expect(bad(STATUS, { field: "status", operator: "is_any_of", value: ["Open"] })).toBeNull();
    expect(bad(ACCOUNT, { field: "account", operator: "is_any_of", value: [] })).toBe("Choose at least one value.");
    expect(bad(ACCOUNT, { field: "account", operator: "is_any_of", value: [4] })).toBeNull();
  });

  it("refuses an operator the column does not offer", () => {
    expect(bad(FLAG, { field: "stale", operator: "contains", value: "x" })).toBe("Choose how to compare.");
    expect(bad(FLAG, { field: "stale", operator: "is_no" })).toBeNull();
  });
});

describe("a condition as the server reads it", () => {
  it("writes numbers with a point and drops a value the operator does not take", () => {
    setLocale({ ...US_ENGLISH, tag: "de-DE", decimal_mark: ",", group_mark: "." });
    expect(toWire(AMOUNT, { field: "value", operator: "at_least", value: "1.234,5" })).toEqual({ field: "value", operator: "at_least", value: "1234.5" });
    expect(toWire(AMOUNT, { field: "value", operator: "between", value: ["1,5", "2"] })).toEqual({ field: "value", operator: "between", value: ["1.5", "2"] });
    expect(toWire(AMOUNT, { field: "value", operator: "is_empty", value: "leftover" })).toEqual({ field: "value", operator: "is_empty" });
    expect(toWire(TEXT, { field: "note", operator: "contains", value: " as typed " })).toEqual({ field: "note", operator: "contains", value: " as typed " });
    expect(toWire(ACCOUNT, { field: "account", operator: "is_any_of", value: [3, 1] })).toEqual({ field: "account", operator: "is_any_of", value: [3, 1] });
  });
});

describe("whether two filters are the same", () => {
  const nodes = new Map([AMOUNT, TEXT].map((n) => [n.key, n]));
  it("ignores order and the way a number was typed", () => {
    const a = [{ field: "value", operator: "at_least", value: "5" }, { field: "note", operator: "contains", value: "x" }];
    const b = [{ field: "note", operator: "contains", value: "x" }, { field: "value", operator: "at_least", value: "5" }];
    expect(sameConditions(a, b, nodes)).toBe(true);
  });
  it("sees a different operator, value or set of conditions", () => {
    const base = [{ field: "value", operator: "at_least", value: "5" }];
    expect(sameConditions(base, [{ field: "value", operator: "at_most", value: "5" }], nodes)).toBe(false);
    expect(sameConditions(base, [{ field: "value", operator: "at_least", value: "6" }], nodes)).toBe(false);
    expect(sameConditions(base, [], nodes)).toBe(false);
    expect(sameConditions([], [], nodes)).toBe(true);
  });
});

describe("a condition in words, for a chip", () => {
  const choices: Choices = { kind: "records", values: [], more: false, options: [{ id: 3, value: "Test dollars", detail: null }, { id: 4, value: "Test euros", detail: null }] };

  it("names the column, the operator and the value", () => {
    expect(say(TEXT, { field: "note", operator: "contains", value: "rent" })).toBe("Note contains rent");
    expect(say(FLAG, { field: "stale", operator: "is_yes" })).toBe("Stale is yes");
    expect(say(STATUS, { field: "status", operator: "is_any_of", value: ["Open", "Closed"] })).toBe("Status is one of Open, Closed");
  });

  it("writes dates and numbers in the person's formats", () => {
    expect(say(DAY, { field: "as_of_date", operator: "after", value: "2025-12-31" })).toBe("Date after Dec 31, 2025");
    expect(say(DAY, { field: "as_of_date", operator: "between", value: ["2025-01-01", "2025-12-31"] })).toBe("Date between Jan 1, 2025 and Dec 31, 2025");
    setLocale({ ...US_ENGLISH, tag: "de-DE", decimal_mark: ",", group_mark: "." });
    expect(say(AMOUNT, { field: "value", operator: "at_least", value: "1234.5" })).toBe("Value at least 1234,5");
  });

  it("names the records a relation's ids stand for, or says how many while they are not known yet", () => {
    expect(say(ACCOUNT, { field: "account", operator: "is_any_of", value: [3, 4] }, choices)).toBe("Account is one of Test dollars, Test euros");
    expect(say(ACCOUNT, { field: "account", operator: "is_any_of", value: [3, 4] })).toBe("Account is one of 2 selected");
    expect(say(ACCOUNT, { field: "account", operator: "is_any_of", value: [3, 99] }, choices)).toBe("Account is one of 2 selected");   // one is not in the list
  });

  it("says what it can about a column the list no longer offers", () => {
    expect(say(undefined, { field: "region", operator: "equals", value: "x" })).toBe("region equals x");
  });
});

describe("the operators of a choice column", () => {
  const SIX = ops("is", "is_not", "is_any_of", "is_not_any_of", "is_empty", "is_not_empty");
  const TYPE = node({ key: "status", path_label: "Status", kind: "choice", operators: SIX, choices: "values", values: ["Open", "Closed"] });
  const WHO = node({ key: "account", path_label: "Account", kind: "choice", operators: SIX, choices: "records" });
  const choices: Choices = { kind: "records", values: [], more: false, options: [{ id: 3, value: "Test dollars", detail: null }, { id: 4, value: "Test euros", detail: null }] };

  it("starts a new condition at “is”, with no choice made yet", () => {
    expect(startCondition(TYPE)).toEqual({ field: "status", operator: "is", value: "" });
    expect(startCondition(WHO)).toEqual({ field: "account", operator: "is", value: "" });
  });

  it("tells which operators take one value", () => {
    expect(isSingleChoice("is")).toBe(true);
    expect(isSingleChoice("is_not")).toBe(true);
    for (const other of ["is_any_of", "is_not_any_of", "is_empty", "is_not_empty", "equals"]) expect(isSingleChoice(other)).toBe(false);
  });

  it("carries a choice between one value and several: one becomes a list of one, and a list becomes its first value", () => {
    expect(withOperator(WHO, { field: "account", operator: "is", value: 3 }, "is_any_of")).toEqual({ field: "account", operator: "is_any_of", value: [3] });
    expect(withOperator(WHO, { field: "account", operator: "is_any_of", value: [4, 3] }, "is_not")).toEqual({ field: "account", operator: "is_not", value: 4 });
    expect(withOperator(TYPE, { field: "status", operator: "is", value: "Open" }, "is_not_any_of")).toEqual({ field: "status", operator: "is_not_any_of", value: ["Open"] });
    expect(withOperator(WHO, { field: "account", operator: "is", value: "" }, "is_any_of")).toEqual({ field: "account", operator: "is_any_of", value: [] });
    expect(withOperator(WHO, { field: "account", operator: "is_any_of", value: [] }, "is")).toEqual({ field: "account", operator: "is", value: "" });
  });

  it("keeps the choice between the two of one kind, and drops it for “empty”, which starts afresh when left", () => {
    expect(withOperator(WHO, { field: "account", operator: "is", value: 3 }, "is_not")).toEqual({ field: "account", operator: "is_not", value: 3 });
    expect(withOperator(WHO, { field: "account", operator: "is_any_of", value: [3, 4] }, "is_not_any_of")).toEqual({ field: "account", operator: "is_not_any_of", value: [3, 4] });
    expect(withOperator(WHO, { field: "account", operator: "is", value: 3 }, "is_empty")).toEqual({ field: "account", operator: "is_empty" });
    expect(withOperator(WHO, { field: "account", operator: "is_empty" }, "is")).toEqual({ field: "account", operator: "is", value: "" });
    expect(withOperator(WHO, { field: "account", operator: "is_not_empty" }, "is_any_of")).toEqual({ field: "account", operator: "is_any_of", value: [] });
  });

  it("is incomplete until one value is chosen for “is” and “is not”, and says so", () => {
    for (const operator of ["is", "is_not"]) {
      expect(problem(WHO, { field: "account", operator, value: "" })).toBe("Choose a value.");
      expect(problem(WHO, { field: "account", operator })).toBe("Choose a value.");
      expect(problem(WHO, { field: "account", operator, value: [3] })).toBe("Choose a value.");           // a list is not one value
      expect(problem(WHO, { field: "account", operator, value: 3 })).toBeNull();
      expect(problem(TYPE, { field: "status", operator, value: "Open" })).toBeNull();
    }
    expect(problem(WHO, { field: "account", operator: "is_not_any_of", value: [] })).toBe("Choose at least one value.");
    expect(problem(WHO, { field: "account", operator: "is_not_any_of", value: [3] })).toBeNull();
  });

  it("is complete with no value for “is empty” and “is not empty”", () => {
    expect(problem(WHO, { field: "account", operator: "is_empty" })).toBeNull();
    expect(problem(TYPE, { field: "status", operator: "is_not_empty" })).toBeNull();
  });

  it("is sent as the value itself for one choice, and with no value for the empties", () => {
    expect(toWire(WHO, { field: "account", operator: "is", value: 3 })).toEqual({ field: "account", operator: "is", value: 3 });
    expect(toWire(TYPE, { field: "status", operator: "is_not", value: "Open" })).toEqual({ field: "status", operator: "is_not", value: "Open" });
    expect(toWire(WHO, { field: "account", operator: "is_empty", value: 3 })).toEqual({ field: "account", operator: "is_empty" });
  });

  it("says a chip in words", () => {
    expect(say(WHO, { field: "account", operator: "is", value: 3 }, choices)).toBe("Account is Test dollars");
    expect(say(WHO, { field: "account", operator: "is_not", value: 4 }, choices)).toBe("Account is not Test euros");
    expect(say(WHO, { field: "account", operator: "is", value: 3 })).toBe("Account is …");                  // the records are not known yet
    expect(say(TYPE, { field: "status", operator: "is_not", value: "Open" })).toBe("Status is not Open");
    expect(say(WHO, { field: "account", operator: "is_not_any_of", value: [3, 4] }, choices)).toBe("Account is not one of Test dollars, Test euros");
    expect(say(WHO, { field: "account", operator: "is_empty" })).toBe("Account is empty");
    expect(say(TYPE, { field: "status", operator: "is_not_empty" })).toBe("Status is not empty");
  });

  it("still reads a filter saved before the relabel, which called the stored name is_any_of", () => {
    expect(problem(WHO, { field: "account", operator: "is_any_of", value: [3] })).toBeNull();
    expect(say(WHO, { field: "account", operator: "is_any_of", value: [3] }, choices)).toBe("Account is one of Test dollars");
  });
});

import { describe, expect, it } from "vitest";
import type { ImportColumn, ImportRead } from "./api";
import { decidedFormat, formatChoices, hiddenSummary, mappingFrom, readiness, setUse, usesFrom, writeCount, writeSummary } from "./importLogic";

const column = (index: number, date_formats: string[] = []): ImportColumn => ({ index, header: `Column ${index}`, samples: [], date_formats });
const read = (columns: ImportColumn[]): ImportRead => ({
  delimiter: ",", row_count: 3, columns, date_formats: ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"],
  suggested: { date: null, balance: null, note: null, currency: null }, today: "2026-10-30",
});

describe("the use of each column", () => {
  it("is worked out from the suggested mapping, and everything else is ignored", () => {
    expect(usesFrom({ date: 0, balance: 2, note: null, currency: null }, 4)).toEqual(["date", "ignore", "balance", "ignore"]);
    expect(usesFrom({ date: null, balance: null, note: null, currency: null }, 2)).toEqual(["ignore", "ignore"]);
  });

  it("turns back into the mapping the server takes, by position", () => {
    expect(mappingFrom(["note", "date", "ignore", "balance"])).toEqual({ date: 1, balance: 3, note: 0, currency: null });
    expect(mappingFrom(usesFrom({ date: 1, balance: 0, note: 3, currency: 2 }, 4))).toEqual({ date: 1, balance: 0, note: 3, currency: 2 });
  });

  it("ignores a suggestion for a column the file does not have", () => {
    expect(usesFrom({ date: 5, balance: 0, note: null, currency: null }, 2)).toEqual(["balance", "ignore"]);
  });

  it("moves a use from the column that had it, so no use is on two columns", () => {
    const start = usesFrom({ date: 0, balance: 1, note: null, currency: null }, 3);
    expect(setUse(start, 2, "date")).toEqual(["ignore", "balance", "date"]);
    expect(setUse(start, 0, "balance")).toEqual(["balance", "ignore", "ignore"]);
  });

  it("lets any number of columns be ignored, and a column change its own use", () => {
    const start = usesFrom({ date: 0, balance: 1, note: null, currency: null }, 3);
    expect(setUse(start, 0, "ignore")).toEqual(["ignore", "balance", "ignore"]);
    expect(setUse(start, 0, "note")).toEqual(["note", "balance", "ignore"]);
    expect(setUse(setUse(start, 2, "ignore"), 1, "ignore")).toEqual(["date", "ignore", "ignore"]);
  });
});

describe("the date format", () => {
  it("is chosen for the person only when the data decides it", () => {
    expect(decidedFormat(column(0, ["DD.MM.YYYY"]))).toBe("DD.MM.YYYY");
    expect(decidedFormat(column(0, ["MM/DD/YYYY", "DD/MM/YYYY"]))).toBeNull();
    expect(decidedFormat(column(0, []))).toBeNull();
    expect(decidedFormat(undefined)).toBeNull();
  });

  it("is chosen from the formats every value fits, or from all of them when none does", () => {
    const all = ["YYYY-MM-DD", "MM/DD/YYYY"];
    expect(formatChoices(column(0, ["MM/DD/YYYY"]), all)).toEqual(["MM/DD/YYYY"]);
    expect(formatChoices(column(0, []), all)).toEqual(all);
    expect(formatChoices(undefined, all)).toEqual(all);
  });
});

describe("whether the mapping can go on", () => {
  const file = read([column(0, ["YYYY-MM-DD"]), column(1), column(2, ["MM/DD/YYYY", "DD/MM/YYYY"])]);

  it("needs a Date and a Balance, and says which is missing", () => {
    expect(readiness(["ignore", "balance", "ignore"], file, null)).toEqual({ ready: false, reason: "Choose which column holds the date." });
    expect(readiness(["date", "ignore", "ignore"], file, "YYYY-MM-DD")).toEqual({ ready: false, reason: "Choose which column holds the balance." });
    expect(readiness(["date", "balance", "ignore"], file, "YYYY-MM-DD")).toEqual({ ready: true, reason: null });
  });

  it("needs the date format chosen when the data could be read two ways", () => {
    expect(readiness(["ignore", "balance", "date"], file, null)).toEqual({ ready: false, reason: "Choose the date format to continue." });
    expect(readiness(["ignore", "balance", "date"], file, "DD/MM/YYYY").ready).toBe(true);
  });

  it("goes on when no format fits, because the review lists the values that are wrong", () => {
    const broken = read([column(0, []), column(1)]);
    expect(readiness(["date", "balance"], broken, null).ready).toBe(true);
  });
});

describe("how the review is described", () => {
  const counts = (add: number, replace: number, unchanged = 0, skip = 0) => ({ add, replace, unchanged, skip });

  it("counts the balances that would be written", () => {
    expect(writeCount(counts(6, 2, 1, 2))).toBe(8);
    expect(writeCount(counts(0, 0, 4, 1))).toBe(0);
  });

  it("says what will be written, or why nothing will", () => {
    expect(writeSummary(counts(1, 0))).toBe("1 balance will be added");
    expect(writeSummary(counts(6, 0))).toBe("6 balances will be added");
    expect(writeSummary(counts(0, 2))).toBe("2 balances will be replaced");
    expect(writeSummary(counts(6, 2))).toBe("6 balances will be added and 2 replaced");
    expect(writeSummary(counts(1200, 0))).toBe("1,200 balances will be added");
    expect(writeSummary(counts(0, 0, 3, 1))).toMatch(/^Nothing will be written/);
  });

  it("says what is not listed", () => {
    expect(hiddenSummary({})).toBe("");
    expect(hiddenSummary({ add: 250, skip: 3 })).toBe("250 more to add, 3 more to skip");
    expect(hiddenSummary({ add: 0, replace: 1 })).toBe("1 more to replace");
  });
});

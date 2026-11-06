import { describe, expect, it } from "vitest";
import type { Conflict } from "./api";
import { conflictBanner, conflictText, rowConflictNote } from "./conflicts";

const conflict = (over: Partial<Conflict> = {}): Conflict => ({
  kind: "changed", account_id: 7, account_name: "Demo Savings", currency: { code: "USD", name: "US Dollar", minor_units: 2 }, date: "2026-03-31", balance_id: 11, version: 9,
  amount_cents: 120000, note: null, by: "Sam Example", on: "2026-11-02", ...over,
});

describe("what a dialog says about a balance that changed", () => {
  it("names the account, the date, who changed it and when, what it is now, and what the person opened it at", () => {
    expect(conflictText(conflict(), 100000)).toBe(
      "Demo Savings on Mar 31, 2026 was changed by Sam Example on Nov 2, 2026. It is now $1,200.00 (you opened it at $1,000.00).");
  });

  it("leaves out what the person opened it at when it is not known", () => {
    expect(conflictText(conflict())).toBe("Demo Savings on Mar 31, 2026 was changed by Sam Example on Nov 2, 2026. It is now $1,200.00.");
  });

  it("says a balance was deleted, and who deleted it", () => {
    expect(conflictText(conflict({ kind: "deleted", amount_cents: null, version: null }))).toBe(
      "The balance for Demo Savings on Mar 31, 2026 was deleted by Sam Example on Nov 2, 2026.");
  });

  it("says a balance was added to a date that had none", () => {
    expect(conflictText(conflict({ kind: "added", amount_cents: 500000 }))).toBe(
      "Demo Savings on Mar 31, 2026 was added by Sam Example on Nov 2, 2026. It is now $5,000.00.");
  });

  it("copes with a change whose author or time is not known", () => {
    expect(conflictText(conflict({ by: null, on: null }))).toBe("Demo Savings on Mar 31, 2026 was changed by someone. It is now $1,200.00.");
    expect(conflictText(conflict({ by: "Sam Example", on: null }))).toContain("changed by Sam Example.");
  });
});

describe("what a row of the Update screen says", () => {
  it("is short, and says what the balance is now", () => {
    expect(rowConflictNote(conflict())).toBe("Changed by Sam Example on Nov 2, 2026: now $1,200.00");
    expect(rowConflictNote(conflict({ kind: "added", amount_cents: 500000 }))).toBe("Added by Sam Example on Nov 2, 2026: now $5,000.00");
    expect(rowConflictNote(conflict({ kind: "deleted", amount_cents: null }))).toBe("Deleted by Sam Example on Nov 2, 2026");
  });

  it("has a banner that counts the balances", () => {
    expect(conflictBanner(1)).toMatch(/^Nothing was saved\. 1 balance changed since you opened this date\. Check the marked row:/);
    expect(conflictBanner(2)).toMatch(/^Nothing was saved\. 2 balances changed since you opened this date\. Check the marked rows:/);
  });
});

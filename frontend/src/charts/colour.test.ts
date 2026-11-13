import { describe, expect, it } from "vitest";
import { slotFor } from "./colour";
import { SLOTS } from "./theme";

describe("the colour of an entity", () => {
  it("comes from its id alone, counted from 1, and the first sixteen of a kind never share one", () => {
    expect(SLOTS).toBe(16);
    const first = Array.from({ length: 16 }, (_, i) => slotFor("account_type", i + 1));
    expect(first).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
    expect(new Set(first).size).toBe(16);
  });

  it("repeats in order past the palette and never gives up: an entity always has a colour", () => {
    expect([17, 18, 32, 33, 34, 1000].map((id) => slotFor("account", id))).toEqual([1, 2, 16, 1, 2, 8]);
    for (let id = 1; id <= 200; id++) {
      const slot = slotFor("account", id)!;
      expect(Number.isInteger(slot) && slot >= 1 && slot <= 16).toBe(true);
    }
  });

  it("is the same whatever else is shown: the same id gives the same colour every time, in any order, in any report", () => {
    const ids = [7, 3, 12, 1, 9];
    const forward = ids.map((id) => slotFor("account_type", id));
    const backward = [...ids].reverse().map((id) => slotFor("account_type", id)).reverse();
    expect(backward).toEqual(forward);
    expect(slotFor("account_type", 7)).toBe(slotFor("account_type", 7));
  });

  it("keeps the kind as a namespace of its own: it names what the id is of, and does not change the slot", () => {
    expect(slotFor("account", 5)).toBe(5);
    expect(slotFor("currency", 5)).toBe(5);
    expect(slotFor("account_type", 21)).toBe(5);
  });

  it("gives no colour to an id that is not a whole number from 1, or to a kind that is not named", () => {
    for (const bad of [0, -1, 1.5, Number.NaN, Infinity, -Infinity]) expect(slotFor("account", bad), String(bad)).toBeUndefined();
    expect(slotFor("", 3)).toBeUndefined();
  });
});

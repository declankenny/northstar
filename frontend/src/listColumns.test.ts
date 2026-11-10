import { describe, expect, it } from "vitest";
import { columnChoice, moved, sameColumns } from "./listColumns";

describe("moving a column", () => {
  const keys = ["a", "b", "c", "d"];

  it("puts the column at its new place and shifts the ones in between", () => {
    expect(moved(keys, 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moved(keys, 3, 0)).toEqual(["d", "a", "b", "c"]);
    expect(moved(keys, 1, 2)).toEqual(["a", "c", "b", "d"]);
  });

  it("does not change the array it was given", () => {
    const before = keys.slice();
    moved(keys, 0, 3);
    expect(keys).toEqual(before);
  });

  it("gives the same array back when nothing moves or a place is outside the list", () => {
    expect(moved(keys, 2, 2)).toBe(keys);
    expect(moved(keys, -1, 2)).toBe(keys);
    expect(moved(keys, 0, 4)).toBe(keys);
    expect(moved([], 0, 0)).toEqual([]);
  });
});

describe("what applying the columns asks of the server", () => {
  const defaults = ["a", "b", "c"];

  it("asks nothing when the columns are as they were, in the same order", () => {
    expect(columnChoice(["a", "b", "c"], ["a", "b", "c"], defaults)).toBeUndefined();
    expect(columnChoice(["c", "a"], ["c", "a"], defaults)).toBeUndefined();
  });

  it("asks for the new columns, in order, when they changed", () => {
    expect(columnChoice(["b", "a", "c"], ["a", "b", "c"], defaults)).toEqual(["b", "a", "c"]);
    expect(columnChoice(["a", "b"], ["a", "b", "c"], defaults)).toEqual(["a", "b"]);
  });

  it("asks to forget the choice when the columns are the list's own again, so a choice is never saved that only repeats the default", () => {
    expect(columnChoice(["a", "b", "c"], ["c", "b", "a"], defaults)).toBeNull();
  });

  it("compares order as well as members", () => {
    expect(sameColumns(["a", "b"], ["b", "a"])).toBe(false);
    expect(sameColumns(["a", "b"], ["a", "b", "c"])).toBe(false);
    expect(sameColumns([], [])).toBe(true);
  });
});

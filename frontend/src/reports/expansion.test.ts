import { describe, expect, it } from "vitest";
import { allFlipped, parentIds } from "./expansion";
import type { HierarchyNode } from "./types";

const node = (id: string, children?: HierarchyNode[]): HierarchyNode => ({ id, label: id, value: 0, children });
const NODES = [node("a", [node("a1", [node("a1x"), node("a1y")]), node("a2")]), node("b"), node("c", [node("c1")])];

describe("the parents of a hierarchy", () => {
  it("are the nodes with nodes inside them, at every depth, and never a node with nothing inside it", () => {
    expect(parentIds(NODES)).toEqual(["a", "a1", "c"]);
    expect(parentIds([node("only")])).toEqual([]);
    expect(parentIds([])).toEqual([]);
  });

  it("are all flipped to open a section that starts closed, and none to close it, and the other way round for one that starts open", () => {
    expect([...allFlipped(NODES, false, true)]).toEqual(["a", "a1", "c"]);
    expect([...allFlipped(NODES, false, false)]).toEqual([]);
    expect([...allFlipped(NODES, true, true)]).toEqual([]);
    expect([...allFlipped(NODES, true, false)]).toEqual(["a", "a1", "c"]);
  });
});

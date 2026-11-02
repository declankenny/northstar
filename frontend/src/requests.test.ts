import { describe, expect, it, vi } from "vitest";
import { fetchTypes, fetchUpdate, fetchVersion } from "./api";

// Every source file of the app as text, by name (the tests themselves are left out).
const files: Record<string, string> = import.meta.glob(["./*.ts", "./*.tsx", "!./*.test.ts", "!./*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
});
const SOURCES = Object.keys(files).map((path) => path.slice(2));
const text = (name: string) => files[`./${name}`];

/** The text of every `useEffect(...)` call in a file, found by matching its brackets. */
function effects(source: string): string[] {
  const found: string[] = [];
  for (let at = source.indexOf("useEffect("); at !== -1; at = source.indexOf("useEffect(", at + 1)) {
    let depth = 0;
    let end = at + "useEffect".length;
    do {
      if (source[end] === "(") depth++;
      if (source[end] === ")") depth--;
      end++;
    } while (depth > 0 && end < source.length);
    found.push(source.slice(at, end));
  }
  return found;
}

describe("how the screens ask the server for things", () => {
  it("looks at the app's own files (so an empty search cannot pass the tests below)", () => {
    expect(SOURCES).toEqual(expect.arrayContaining(["api.ts", "Dashboard.tsx", "UpdateBalances.tsx", "useRequest.ts"]));
    expect(SOURCES.some((name) => name.includes(".test."))).toBe(false);
  });

  it("only api.ts calls fetch, so every request can be cancelled through one place", () => {
    const offenders = SOURCES.filter((name) => name !== "api.ts" && /\bfetch\(/.test(text(name)));
    expect(offenders).toEqual([]);
  });

  it("no useEffect loads data itself: loading goes through useRequest, which ignores an old answer", () => {
    const offenders = SOURCES.filter((name) => name !== "useRequest.ts")
      .filter((name) => effects(text(name)).some((effect) => /\bfetch[A-Z]\w*\(/.test(effect)));
    expect(offenders).toEqual([]);
  });

  it("the scan itself sees an effect that loads (so the test above can fail)", () => {
    const sample = "useEffect(() => { fetchThing().then(setThing); }, []);\nuseEffect(() => { document.title = 'a'; }, []);";
    expect(effects(sample).filter((effect) => /\bfetch[A-Z]\w*\(/.test(effect))).toHaveLength(1);
  });
});

describe("the signal reaches the browser's fetch", () => {
  it.each([
    ["fetchTypes", (signal: AbortSignal) => fetchTypes(signal)],
    ["fetchUpdate", (signal: AbortSignal) => fetchUpdate("2026-10-30", signal)],
    ["fetchVersion", (signal: AbortSignal) => fetchVersion(signal)],
  ])("%s", async (_name, load) => {
    const answer = { ok: true, status: 200, json: async () => ({ version: "1" }) };
    const stub = vi.fn().mockResolvedValue(answer);
    vi.stubGlobal("fetch", stub);
    try {
      const controller = new AbortController();
      await load(controller.signal);
      expect(stub.mock.calls[0][1].signal).toBe(controller.signal);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

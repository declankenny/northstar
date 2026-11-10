// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportList } from "./api";
import { fileNameOf, saveFile } from "./download";

beforeEach(() => {
  vi.useFakeTimers();
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("saving a file the page already has", () => {
  it("hands the browser a link to it that is named and clicked, and leaves nothing in the page", () => {
    const clicked: { href: string; download: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push({ href: this.href, download: this.download }); });
    const blob = new Blob(["a,b\r\n"], { type: "text/csv" });
    saveFile(blob, "northstar-balances-2026-11-10.csv");
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([{ href: "blob:test", download: "northstar-balances-2026-11-10.csv" }]);
    expect(document.querySelector("a")).toBeNull();
  });

  it("lets go of the file's address once the browser has taken it, and not before", () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    saveFile(new Blob(["x"]), "x.csv");
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test");
  });

  it("reads the name the server gave, and has a fallback when it gave none", () => {
    expect(fileNameOf('attachment; filename="northstar-balances-2026-11-10.csv"', "x.csv")).toBe("northstar-balances-2026-11-10.csv");
    expect(fileNameOf("attachment", "balances.csv")).toBe("balances.csv");
    expect(fileNameOf(null, "balances.csv")).toBe("balances.csv");
  });
});

describe("exporting a list", () => {
  const answer = (init: ResponseInit & { body?: BodyInit } = {}) => new Response(init.body ?? "﻿Date\r\n", {
    status: 200, headers: { "Content-Disposition": 'attachment; filename="northstar-balances-2026-11-10.csv"', "Content-Type": "text/csv" }, ...init,
  });

  it("posts the list's view to its own address, without the page and the page size, and saves what comes back under the name it was given", async () => {
    const fetched = vi.fn().mockResolvedValue(answer());
    vi.stubGlobal("fetch", fetched);
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    await exportList("balances", { page: 3, page_size: 50, search: "rent", sort: { field: "as_of_date", direction: "desc" }, group: "account.type",
      filters: [{ field: "note", operator: "contains", value: "x" }] });
    const [url, init] = fetched.mock.calls[0];
    expect(url).toBe("/api/lists/balances/export");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ search: "rent", sort: { field: "as_of_date", direction: "desc" }, group: "account.type",
      filters: [{ field: "note", operator: "contains", value: "x" }] });
    const saved = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect(saved.size).toBeGreaterThan(0);
    expect(names).toEqual(["northstar-balances-2026-11-10.csv"]);                      // the name the server gave, not one made up here
  });

  it("sends nothing about columns or filters when the view names none, so the server uses the person's own", async () => {
    const fetched = vi.fn().mockResolvedValue(answer());
    vi.stubGlobal("fetch", fetched);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await exportList("balances", { page: 1 });
    expect(JSON.parse(fetched.mock.calls[0][1].body)).toEqual({});
  });

  it("keeps the file's bytes as they came, with the byte-order mark in front", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({ body: new Uint8Array([0xef, 0xbb, 0xbf, 0x44]) })));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await exportList("balances", { page: 1 });
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(new Uint8Array([0xef, 0xbb, 0xbf, 0x44]));
  });

  it("encodes the list's key in the address", async () => {
    const fetched = vi.fn().mockResolvedValue(answer());
    vi.stubGlobal("fetch", fetched);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await exportList("odd key/x", { page: 1 });
    expect(fetched.mock.calls[0][0]).toBe("/api/lists/odd%20key%2Fx/export");
  });

  it("says why the server refused, in its words, and saves nothing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Value cannot be grouped." }), { status: 422 })));
    await expect(exportList("balances", { page: 1, group: "amount_cents" })).rejects.toThrow("Value cannot be grouped.");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("says what it can when the answer is not the server's own words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 502 })));
    await expect(exportList("balances", { page: 1 })).rejects.toThrow("The server answered 502");
  });
});

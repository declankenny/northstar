// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The router keeps its state in the module, so each test loads a fresh copy and sets up the browser's history first.
async function load(startPath: string, idx = 0) {
  window.history.replaceState({ idx }, "", startPath);
  vi.resetModules();
  return await import("./router");
}

const here = () => window.location.pathname;

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("goBack", () => {
  it("returns to the page of the app this one was opened from, like the browser's Back button", async () => {
    const router = await load("/accounts/7");
    router.navigate("/accounts/7/import");
    expect(here()).toBe("/accounts/7/import");
    expect(router.goBack("/somewhere-else")).toBe(true);
    await vi.waitFor(() => expect(here()).toBe("/accounts/7"));
  });

  it("goes to the fallback when there is no earlier page of the app (opened directly or in a new tab)", async () => {
    const router = await load("/accounts/7/import", 0);
    expect(router.goBack("/accounts/7")).toBe(true);
    expect(here()).toBe("/accounts/7");
    expect(router.goBack("/nowhere")).toBe(true);        // the fallback is itself a page that can be returned from
    await vi.waitFor(() => expect(here()).toBe("/accounts/7/import"));
  });

  it("does not count pages of other sites: only an index kept by the app says there is a page to go back to", async () => {
    const router = await load("/accounts/7/import", 0);
    window.history.pushState(null, "", "/elsewhere");     // history.length grows, but the app did not do it
    window.history.replaceState({ idx: 0 }, "", "/accounts/7/import");
    router.goBack("/accounts/7");
    expect(here()).toBe("/accounts/7");
  });

  it("asks a leave guard once, and does nothing when it refuses", async () => {
    const router = await load("/accounts/7");
    router.navigate("/accounts/7/import");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderHook(() => router.useLeaveGuard(true, "Leave this page?"));
    expect(router.goBack("/fallback")).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledWith("Leave this page?");
    expect(here()).toBe("/accounts/7/import");
  });

  it("asks only once when the person agrees, even though going back is a navigation of its own", async () => {
    const router = await load("/accounts/7");
    router.navigate("/accounts/7/import");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderHook(() => router.useLeaveGuard(true, "Leave this page?"));
    expect(router.goBack("/fallback")).toBe(true);
    await vi.waitFor(() => expect(here()).toBe("/accounts/7"));
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("does not leave the guard switched off for the next time", async () => {
    const router = await load("/accounts/7");
    router.navigate("/accounts/7/import");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderHook(() => router.useLeaveGuard(true, "Leave this page?"));
    router.goBack("/fallback");
    await vi.waitFor(() => expect(here()).toBe("/accounts/7"));
    router.navigate("/accounts");                          // an ordinary move asks again
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("still asks when the browser's own Back button is used", async () => {
    const router = await load("/accounts/7");
    router.navigate("/accounts/7/import");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderHook(() => router.useLeaveGuard(true, "Leave this page?"));
    window.history.back();
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(here()).toBe("/accounts/7/import"));   // put back, because the person stayed
  });
});

describe("navigate", () => {
  it("records where it is in the app's own history, so goBack can tell", async () => {
    const router = await load("/a");
    router.navigate("/b");
    expect(window.history.state).toEqual({ idx: 1 });
    router.navigate("/c");
    expect(window.history.state).toEqual({ idx: 2 });
  });
});

describe("the address's query string", () => {
  it("useSearch follows the query string through navigate and Back", async () => {
    const router = await load("/balances");
    const { result } = renderHook(() => router.useSearch());
    expect(result.current).toBe("");
    act(() => { router.navigate("/balances?sort=-account"); });
    expect(result.current).toBe("?sort=-account");
    act(() => { router.navigate("/balances?sort=-account&page=2"); });
    expect(result.current).toBe("?sort=-account&page=2");
    act(() => { window.history.back(); });
    await vi.waitFor(() => expect(result.current).toBe("?sort=-account"));
  });

  it("replaceAddress changes the address without adding a history entry, and says so to the page", async () => {
    const router = await load("/balances");
    const { result } = renderHook(() => ({ search: router.useSearch(), path: router.usePath() }));
    const entry = () => (window.history.state as { idx: number }).idx;
    const before = entry();
    act(() => router.replaceAddress("/balances?q=av"));
    expect(result.current).toEqual({ search: "?q=av", path: "/balances" });
    act(() => router.replaceAddress("/balances?q=ave"));
    expect(result.current.search).toBe("?q=ave");
    expect(entry()).toBe(before);                                                 // still the same entry, so Back leaves the page
  });

  it("replaceAddress to the address it is already at changes nothing", async () => {
    const router = await load("/balances?q=av");
    const replace = vi.spyOn(window.history, "replaceState");
    router.replaceAddress("/balances?q=av");
    expect(replace).not.toHaveBeenCalled();
  });
});

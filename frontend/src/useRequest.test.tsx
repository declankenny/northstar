// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { deferred } from "./testing";
import { useLatest, useRequest } from "./useRequest";

afterEach(cleanup);

/** A loader that hands out one deferred answer per call, remembering the signal each was given. */
function loader<T>() {
  const calls: { reply: ReturnType<typeof deferred<T>>; signal: AbortSignal }[] = [];
  const load = (signal: AbortSignal) => {
    const reply = deferred<T>();
    calls.push({ reply, signal });
    return reply.promise;
  };
  return { calls, load };
}

describe("useRequest", () => {
  it("is loading until the answer arrives, then has the data", async () => {
    const { calls, load } = loader<string>();
    const { result } = renderHook(() => useRequest(load, []));
    expect(result.current).toMatchObject({ data: null, error: null, loading: true });
    await act(async () => calls[0].reply.resolve("hello"));
    expect(result.current).toMatchObject({ data: "hello", error: null, loading: false });
  });

  it("ignores an answer once its inputs have changed, and cancels the request", async () => {
    const { calls, load } = loader<string>();
    const { result, rerender } = renderHook(({ id }) => useRequest(load, [id]), { initialProps: { id: 1 } });
    rerender({ id: 2 });
    expect(calls).toHaveLength(2);
    expect(calls[0].signal.aborted).toBe(true);
    expect(calls[1].signal.aborted).toBe(false);

    await act(async () => calls[1].reply.resolve("two"));
    await act(async () => calls[0].reply.resolve("one"));   // arrives late
    expect(result.current.data).toBe("two");
  });

  it("ignores a late failure of an old request", async () => {
    const { calls, load } = loader<string>();
    const { result, rerender } = renderHook(({ id }) => useRequest(load, [id]), { initialProps: { id: 1 } });
    rerender({ id: 2 });
    await act(async () => calls[1].reply.resolve("two"));
    await act(async () => calls[0].reply.reject(new Error("boom")));
    expect(result.current).toMatchObject({ data: "two", error: null });
  });

  it("does not report a cancelled request as an error", async () => {
    const { calls, load } = loader<string>();
    const { result, rerender } = renderHook(({ id }) => useRequest(load, [id]), { initialProps: { id: 1 } });
    rerender({ id: 2 });
    await act(async () => calls[0].reply.reject(new DOMException("Aborted", "AbortError")));
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(true);   // the second request is still on its way
  });

  it("reports the error of the current request, and clears it when asked again", async () => {
    const { calls, load } = loader<string>();
    const { result } = renderHook(() => useRequest(load, []));
    await act(async () => calls[0].reply.reject(new Error("The server answered 500")));
    expect(result.current).toMatchObject({ data: null, error: "The server answered 500", loading: false });
    act(() => result.current.reload());
    expect(result.current).toMatchObject({ error: null, loading: true });
    await act(async () => calls[1].reply.resolve("fine"));
    expect(result.current).toMatchObject({ data: "fine", error: null });
  });

  it("keeps the last data while the next loads, or clears it with reset", async () => {
    const keep = loader<string>();
    const kept = renderHook(({ id }) => useRequest(keep.load, [id]), { initialProps: { id: 1 } });
    await act(async () => keep.calls[0].reply.resolve("one"));
    kept.rerender({ id: 2 });
    expect(kept.result.current).toMatchObject({ data: "one", loading: true });

    const wipe = loader<string>();
    const wiped = renderHook(({ id }) => useRequest(wipe.load, [id], { reset: true }), { initialProps: { id: 1 } });
    await act(async () => wipe.calls[0].reply.resolve("one"));
    wiped.rerender({ id: 2 });
    expect(wiped.result.current).toMatchObject({ data: null, loading: true });
  });

  it("asks again for the same inputs on reload, and the old answer cannot overwrite the new one", async () => {
    const { calls, load } = loader<string>();
    const { result } = renderHook(() => useRequest(load, []));
    act(() => result.current.reload());
    expect(calls).toHaveLength(2);
    await act(async () => calls[1].reply.resolve("new"));
    await act(async () => calls[0].reply.resolve("old"));
    expect(result.current.data).toBe("new");
  });

  it("waits while skip is set, and loads once it is not", async () => {
    const { calls, load } = loader<string>();
    const { result, rerender } = renderHook(({ ready }) => useRequest(load, [], { skip: !ready }), { initialProps: { ready: false } });
    expect(calls).toHaveLength(0);
    expect(result.current.loading).toBe(false);
    rerender({ ready: true });
    expect(calls).toHaveLength(1);
    await act(async () => calls[0].reply.resolve("ready"));
    expect(result.current.data).toBe("ready");
  });

  it("setData puts in the answer to a change and drops a load still on its way", async () => {
    const { calls, load } = loader<string[]>();
    const { result } = renderHook(() => useRequest(load, []));
    await act(async () => calls[0].reply.resolve(["a"]));
    act(() => result.current.reload());
    act(() => result.current.setData((list) => [...(list ?? []), "b"]));
    expect(result.current.data).toEqual(["a", "b"]);
    expect(calls[1].signal.aborted).toBe(true);
    await act(async () => calls[1].reply.resolve(["stale"]));
    expect(result.current.data).toEqual(["a", "b"]);
  });

  it("cancels the request when the screen is left", () => {
    const { calls, load } = loader<string>();
    const { unmount } = renderHook(() => useRequest(load, []));
    unmount();
    expect(calls[0].signal.aborted).toBe(true);
  });
});

describe("useLatest", () => {
  it("makes only the newest ticket current, and none once the screen is left", () => {
    const { result, unmount } = renderHook(() => useLatest());
    const first = result.current();
    const second = result.current();
    expect(first.current()).toBe(false);
    expect(first.signal.aborted).toBe(true);
    expect(second.current()).toBe(true);
    unmount();
    expect(second.current()).toBe(false);
  });
});

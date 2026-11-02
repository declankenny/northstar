// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UpdatePage } from "./api";
import { deferred } from "./testing";
import { UpdateBalances } from "./UpdateBalances";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchUpdate: vi.fn() }));

import { fetchUpdate } from "./api";

afterEach(cleanup);

describe("Update balances: reading a date", () => {
  it("is cancelled when the screen is left, and a late answer or failure is not shown", async () => {
    const reply = deferred<UpdatePage>();
    vi.mocked(fetchUpdate).mockReturnValue(reply.promise);
    const { unmount } = render(<UpdateBalances />);
    const signal = vi.mocked(fetchUpdate).mock.calls[0][1]!;
    expect(signal.aborted).toBe(false);

    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => reply.reject(new Error("The server answered 500")));   // nothing to update, and no error thrown
    expect(screen.queryByText(/Could not load/)).toBeNull();
  });
});

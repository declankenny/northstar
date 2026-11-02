// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NetWorthSeries } from "./api";
import { Dashboard } from "./Dashboard";
import { deferred } from "./testing";

vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), fetchNetWorth: vi.fn() }));
// The chart draws an SVG that needs real layout; what matters here is which series it was handed.
vi.mock("./NetWorthChart", () => ({ NetWorthChart: ({ data }: { data: NetWorthSeries }) => <div data-testid="chart">{data.start}</div> }));

import { fetchNetWorth } from "./api";

const TODAY = "2026-10-30";
const answer = (start: string): NetWorthSeries => ({
  today: TODAY, start, end: TODAY, period: "week",
  series: [{ date: start, assets: 100000, liabilities: 0, net_worth: 100000 }],
});

describe("Dashboard", () => {
  const pending: { start: string | undefined; reply: ReturnType<typeof deferred<NetWorthSeries>> }[] = [];

  beforeEach(() => {
    pending.length = 0;
    vi.mocked(fetchNetWorth).mockImplementation((options) => {
      if (!options) return Promise.resolve(answer("2020-01-01")); // the first request only learns the server's today
      const reply = deferred<NetWorthSeries>();
      pending.push({ start: options.start, reply });
      return reply.promise;
    });
  });
  afterEach(cleanup);

  /** Show the default range, then choose two more before either has answered. Returns the two requests, in the order asked. */
  async function chooseTwoRanges() {
    render(<Dashboard />);
    await vi.waitFor(() => expect(pending).toHaveLength(1)); // the default range, 1Y
    await act(async () => pending[0].reply.resolve(answer("2025-10-30")));
    fireEvent.click(screen.getByRole("button", { name: "1M" }));
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "3M" }));
    await vi.waitFor(() => expect(pending).toHaveLength(3));
    return { first: pending[1].reply, second: pending[2].reply };
  }

  it("shows the range chosen last, even when an earlier range's answer arrives after it", async () => {
    const { first, second } = await chooseTwoRanges();
    await act(async () => second.resolve(answer("2026-07-30")));  // 3M answers first
    expect(screen.getByTestId("chart").textContent).toBe("2026-07-30");
    await act(async () => first.resolve(answer("2026-09-30")));   // then the old 1M answer arrives
    expect(screen.getByTestId("chart").textContent).toBe("2026-07-30");
    expect(screen.getByRole("button", { name: "3M" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("does not show an error from a range that is no longer the one chosen", async () => {
    const { first, second } = await chooseTwoRanges();
    await act(async () => second.resolve(answer("2026-07-30")));
    await act(async () => first.reject(new Error("The server answered 500")));
    expect(screen.queryByText(/Could not load/)).toBeNull();
    expect(screen.getByTestId("chart").textContent).toBe("2026-07-30");
  });
});

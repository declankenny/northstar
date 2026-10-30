import type { Period } from "./api";
import { addMonths } from "./dates";

// A range is only a start date and how finely to sample. The server does the rest: it works out
// every number, and it never starts before the first balance.
export const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y", "ALL"] as const;
export type Range = (typeof RANGES)[number];

/** Fine enough to see the shape, coarse enough to stay well under the server's point limit. */
export const PERIOD: Record<Range, Period> = {
  "1M": "day", "3M": "day", "6M": "week", YTD: "week", "1Y": "week", "5Y": "month", ALL: "month",
};

const MONTHS_BACK: Record<string, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60 };

/** Where the range starts, or undefined for "from the first balance". */
export function rangeStart(range: Range, today: string): string | undefined {
  if (range === "ALL") return undefined;
  if (range === "YTD") return `${today.slice(0, 4)}-01-01`;
  return addMonths(today, -MONTHS_BACK[range]);
}

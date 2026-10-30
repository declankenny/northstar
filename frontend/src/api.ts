/** One point of the series: the totals on a date, in integer cents. */
export type Point = { date: string; assets: number; liabilities: number; net_worth: number };

export type Period = "day" | "week" | "month";

export type NetWorthSeries = {
  today: string; // the server's today(), so the page never reads the browser's clock
  start: string; // the dates actually used: the server never starts before the first balance
  end: string;
  period: Period;
  series: Point[];
};

/** Net worth at regular dates. With no start the server begins at the first balance. */
export async function fetchNetWorth(query: { start?: string; period?: Period } = {}): Promise<NetWorthSeries> {
  const params = new URLSearchParams();
  if (query.start) params.set("start", query.start);
  if (query.period) params.set("period", query.period);
  const response = await fetch(`/api/networth?${params}`);
  if (!response.ok) throw new Error(`The server answered ${response.status}`);
  return response.json();
}

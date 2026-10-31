import { useEffect, useState } from "react";
import { fetchNetWorth, type NetWorthSeries } from "./api";
import { formatDate } from "./dates";
import { NetWorthChart } from "./NetWorthChart";
import { PERIOD, RANGES, type Range, rangeStart } from "./ranges";
import { Tile, WHEN } from "./Tile";

export function Dashboard() {
  const [today, setToday] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("1Y");
  const [view, setView] = useState<{ range: Range; data: NetWorthSeries } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The first request, with no dates, only learns the server's today. Ranges are worked out from it.
  useEffect(() => {
    fetchNetWorth().then((data) => setToday(data.today), (e: Error) => setError(e.message));
  }, []);

  // Every range is a request for that window. The server does all the arithmetic.
  useEffect(() => {
    if (today === null) return;
    let current = true; // ignore an answer that arrives after another range was chosen
    fetchNetWorth({ start: rangeStart(range, today), period: PERIOD[range] }).then(
      (data) => { if (current) setView({ range, data }); },
      (e: Error) => { if (current) setError(e.message); },
    );
    return () => { current = false; };
  }, [today, range]);

  if (error) return <p className="empty">Could not load net worth. {error}.</p>;
  if (!view) return <p className="empty">Loading…</p>;

  const { data } = view;
  const first = data.series[0];
  const last = data.series[data.series.length - 1];
  const when = WHEN[view.range];
  return (
    <>
      <div className="top">
        <div>
          <div className="eyebrow">{formatDate(data.today).toUpperCase()}</div>
          <h1>Dashboard</h1>
        </div>
        <a className="btn" href="/balances/update">Update balances</a>
      </div>

      {data.series.length === 0 ? (
        <div className="empty">
          <p>Nothing to show yet.</p>
          <p>Add an account on <a href="#/accounts">Accounts</a>, then enter its first balance on <a href="/balances/update">Update balances</a>.</p>
        </div>
      ) : (
        <>
          <div className="tiles">
            <Tile main label="Net worth" value={last.net_worth} first={first.net_worth} goodWhenUp when={when} />
            <Tile label="Assets" value={last.assets} first={first.assets} goodWhenUp when={when} />
            {/* Owing less is good news, so a falling liability is the green one. */}
            <Tile label="Liabilities" value={last.liabilities} first={first.liabilities} goodWhenUp={false} when={when} />
          </div>

          <div className="charthead">
            <span className="label">Net worth history</span>
            <div className="ranges" role="group" aria-label="Date range">
              {RANGES.map((r) => (
                <button key={r} className={r === range ? "on" : ""} aria-pressed={r === range} onClick={() => setRange(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <NetWorthChart data={data} />
        </>
      )}
    </>
  );
}

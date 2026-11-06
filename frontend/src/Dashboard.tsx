import { useState } from "react";
import { fetchNetWorth, type NetWorthSeries } from "./api";
import { formatDate } from "./dates";
import { NetWorthChart } from "./NetWorthChart";
import { PERIOD, RANGES, type Range, rangeStart } from "./ranges";
import { Link } from "./router";
import { currencyPath, PATHS } from "./routes";
import { Tile, WHEN } from "./Tile";
import { useRequest } from "./useRequest";

const names = (codes: string[]) => (codes.length < 2 ? codes.join("") : `${codes.slice(0, -1).join(", ")} and ${codes[codes.length - 1]}`);

/** Why the chart does not reach as far back as it was asked to, or why it is empty: a currency has no rate before a date. Admins are
 *  offered the page where earlier rates are added. */
function LimitedNote({ limited, isAdmin }: { limited: NonNullable<NetWorthSeries["limited"]>; isAdmin: boolean }) {
  const { starts_on, currencies } = limited;
  const have = currencies.length === 1 ? "has" : "have";
  return (
    <p className="notice warn" role="status">
      {starts_on ? `Starts ${formatDate(starts_on)}: ${names(currencies)} ${have} no rate before this.`
        : `Net worth cannot be shown yet: ${names(currencies)} ${have} no rate for these dates.`}
      {isAdmin && currencies.map((code) => <span key={code}> <Link to={currencyPath(code)}>Add earlier {code} rates</Link></span>)}
    </p>
  );
}

export function Dashboard({ isAdmin = false }: { isAdmin?: boolean } = {}) {
  const [range, setRange] = useState<Range>("1Y");

  // The first request, with no dates, only learns the server's today. Ranges are worked out from it.
  const learnedToday = useRequest((signal) => fetchNetWorth(undefined, signal), []);
  const today = learnedToday.data?.today ?? null;

  // Every range is a request for that window. The server does all the arithmetic. The answer says which range it is for.
  const windowed = useRequest(
    async (signal) => ({ range, data: await fetchNetWorth({ start: rangeStart(range, today!), period: PERIOD[range] }, signal) }),
    [today, range],
    { skip: today === null },
  );

  const error = learnedToday.error ?? windowed.error;
  const view = windowed.data;
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
      </div>

      {data.series.length === 0 && data.limited ? (
        <LimitedNote limited={data.limited} isAdmin={isAdmin} />
      ) : data.series.length === 0 ? (
        <div className="empty">
          <p>Nothing to show yet.</p>
          <p>Add an account on <Link to={PATHS.accounts}>Accounts</Link>, then enter its first balance on <Link to={PATHS.update}>Update balances</Link>.</p>
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
          {data.limited && <LimitedNote limited={data.limited} isAdmin={isAdmin} />}
        </>
      )}
    </>
  );
}

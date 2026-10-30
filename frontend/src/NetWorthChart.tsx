import { useState } from "react";
import type { NetWorthSeries } from "./api";
import { dayNumber, formatDate } from "./dates";
import { formatCents } from "./money";

const W = 1000;
const H = 400;
const TOP = 24;
const BOTTOM = 10;

// An area chart of the samples the server sent. There is no axis on purpose: this is the big
// picture, and the tooltip has the numbers. It draws what it is given and works nothing out.
export function NetWorthChart({ data }: { data: NetWorthSeries }) {
  const [hover, setHover] = useState<number | null>(null); // index of the nearest sample
  const { series } = data;
  const startDay = dayNumber(data.start);
  const span = Math.max(dayNumber(data.end) - startDay, 1);

  const values = series.map((p) => p.net_worth);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const room = Math.max(hi - lo, 1);
  const min = lo - room * 0.25;
  const max = hi + room * 0.15;

  const xs = series.map((p) => ((dayNumber(p.date) - startDay) / span) * W);
  const y = (v: number) => TOP + (1 - (v - min) / (max - min)) * (H - TOP - BOTTOM);
  const coords = series.map((p, i) => [xs[i], y(p.net_worth)]);
  if (coords.length === 1) coords.push([W, coords[0][1]]); // one sample: a flat line across

  const line = coords.map(([cx, cy], i) => `${i === 0 ? "M" : "L"}${cx},${cy}`).join(" ");
  const area = `${line} L${coords[coords.length - 1][0]},${H} L${coords[0][0]},${H} Z`;
  const point = hover === null ? null : series[hover];

  return (
    <div
      className="chartwrap"
      onMouseMove={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        const f = Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1);
        const wanted = startDay + f * span;
        let nearest = 0;
        series.forEach((p, i) => {
          if (Math.abs(dayNumber(p.date) - wanted) < Math.abs(dayNumber(series[nearest].date) - wanted)) nearest = i;
        });
        setHover(nearest);
      }}
      onMouseLeave={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Net worth over time">
        <defs>
          <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity=".34" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#fill)" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {hover !== null && (
          <line x1={xs[hover]} x2={xs[hover]} y1="0" y2={H} stroke="var(--muted)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {hover !== null && point && (
        <div
          className="tip num"
          style={{
            left: `${(xs[hover] / W) * 100}%`,
            transform: xs[hover] / W > 0.7 ? "translateX(calc(-100% - 14px))" : "translateX(14px)",
          }}
        >
          <span>{formatDate(point.date)}</span>
          <b>{formatCents(point.net_worth)}</b>
          <span>Assets {formatCents(point.assets)}<br />Liabilities {formatCents(point.liabilities)}</span>
        </div>
      )}
    </div>
  );
}

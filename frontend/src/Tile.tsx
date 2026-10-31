import { formatCents, percentChange } from "./money";

export const WHEN: Record<string, string> = {
  "1M": "past month", "3M": "past 3 months", "6M": "past 6 months", YTD: "year to date",
  "1Y": "past year", "5Y": "past 5 years", ALL: "all time",
};

/** A total with its change over the chosen range. goodWhenUp is false for money owed: owing less is good news. */
export function Tile(props: { label: string; value: number; first: number; goodWhenUp: boolean; when: string; main?: boolean }) {
  const diff = props.value - props.first;
  const pct = percentChange(diff, props.first);
  const good = diff === 0 ? null : diff > 0 === props.goodWhenUp;
  const sign = diff >= 0 ? "+" : "-";
  return (
    <div className={props.main ? "tile main" : "tile"}>
      <div className="label">{props.label}</div>
      <div className="val num">{formatCents(props.value)}</div>
      <div className="delta num">
        <span className={good === null ? "m" : good ? "p" : "n"}>
          {sign}{formatCents(Math.abs(diff))}{pct === null ? "" : ` (${sign}${Math.abs(pct).toFixed(1)}%)`}
        </span>{" "}
        <span className="m">{props.when}</span>
      </div>
    </div>
  );
}

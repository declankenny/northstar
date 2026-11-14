import { useMemo } from "react";
import { Chart, type ChartClick } from "./Chart";
import { useChartTheme } from "./theme";
import { axisRange, BRACKET, bridgeBars, scaleOption, type StepNode, waterfallOption, type Whole, type Words } from "./waterfall";

/** The room a step has along the chart, in pixels. A bridge with many steps is wider than its card, and scrolls sideways. */
const ROOM_PER_BAR = 104;
const LEAST_WIDTH = 480;

/** A waterfall: an opening bar, a step for each of `nodes` from the running total, and a closing bar. The scale is a column of its own that
 *  stays put while the bars scroll beside it. The chart is a picture, and its marks cannot be reached by keyboard: a screen reader is given
 *  the figures in its description, and a report shows the same nodes as a table beside it. `whole` is the opening and closing total when it is
 *  more than the steps add up to. `words` says how an amount is written. */
export function WaterfallChart({ nodes, whole, words, label, isOpen, onToggle, onOpen }: {
  nodes: StepNode[]; whole?: Whole; words: Words; label: string; isOpen?: (id: string) => boolean; onToggle?: (id: string) => void; onOpen?: (href: string) => void;
}) {
  const theme = useChartTheme();
  const bars = useMemo(() => bridgeBars(nodes, whole, isOpen), [nodes, whole, isOpen]);
  const range = useMemo(() => axisRange(bars), [bars]);
  const option = useMemo(() => waterfallOption(bars, range, theme, words), [bars, range, theme, words]);
  const scale = useMemo(() => scaleOption(range, theme, words, bars), [range, theme, words, bars]);
  const description = `${label}: ${bars.map((b) => `${b.name} ${b.kind === "total" ? words.amount(b.value) : words.change(b.value)}`).join(", ")}`;
  // A click on a type's bar, or on its name under the axis, opens it; on the name of an open type's bracket, closes it; on an account's bar, opens
  // the account. The ids are the bars', and what a click on an axis says is the id of its bar.
  const clicked = ({ data, axis }: ChartClick) => {
    const id = axis ?? (data as { id?: string } | undefined)?.id;
    if (!id) return;
    if (id.startsWith(BRACKET)) return onToggle?.(id.slice(BRACKET.length));
    const bar = bars.find((b) => b.id === id);
    if (bar?.expandable) onToggle?.(bar.id);
    else if (bar?.href && !axis) onOpen?.(bar.href);
  };
  return (
    <div className="bridge-chart">
      <div className="bridge-axis" aria-hidden="true"><Chart option={scale} label="Scale" /></div>
      <div className="bridge-scroll">
        <div style={{ minWidth: Math.max(LEAST_WIDTH, bars.length * ROOM_PER_BAR) }}><Chart option={option} label={description} onClick={clicked} /></div>
      </div>
    </div>
  );
}

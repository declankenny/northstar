import { useMemo } from "react";
import { Chart } from "./Chart";
import { useChartTheme } from "./theme";
import { axisRange, bridgeBars, scaleOption, type StepNode, waterfallOption, type Whole, type Words } from "./waterfall";

/** The room a step has along the chart, in pixels. A bridge with many steps is wider than its card, and scrolls sideways. */
const ROOM_PER_BAR = 104;
const LEAST_WIDTH = 480;

/** A waterfall: an opening bar, a step for each of `nodes` from the running total, and a closing bar. The scale is a column of its own that
 *  stays put while the bars scroll beside it. The chart is a picture, and its marks cannot be reached by keyboard: a screen reader is given
 *  the figures in its description, and a report shows the same nodes as a table beside it. `whole` is the opening and closing total when it is
 *  more than the steps add up to. `words` says how an amount is written. */
export function WaterfallChart({ nodes, whole, words, label }: { nodes: StepNode[]; whole?: Whole; words: Words; label: string }) {
  const theme = useChartTheme();
  const bars = useMemo(() => bridgeBars(nodes, whole), [nodes, whole]);
  const range = useMemo(() => axisRange(bars), [bars]);
  const option = useMemo(() => waterfallOption(bars, range, theme, words), [bars, range, theme, words]);
  const scale = useMemo(() => scaleOption(range, theme, words), [range, theme, words]);
  const description = `${label}: ${bars.map((b) => `${b.name} ${b.kind === "total" ? words.amount(b.value) : words.change(b.value)}`).join(", ")}`;
  return (
    <div className="bridge-chart">
      <div className="bridge-axis" aria-hidden="true"><Chart option={scale} label="Scale" /></div>
      <div className="bridge-scroll">
        <div style={{ minWidth: Math.max(LEAST_WIDTH, bars.length * ROOM_PER_BAR) }}><Chart option={option} label={description} /></div>
      </div>
    </div>
  );
}

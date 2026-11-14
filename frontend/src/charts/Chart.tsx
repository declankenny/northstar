import { useEffect, useRef } from "react";
import { echarts, type EChartsCoreOption } from "./echarts";

/** What a click says: on a mark, its name and the data item the chart was given; on the label of an axis (a chart asks for these with
 *  `triggerEvent`), that label's value in `axis`. */
export type ChartClick = { name: string; data?: unknown; axis?: string };

/** One ECharts chart, drawn as SVG from `option`, which the caller builds from the theme and the data, so a new option is a new
 *  picture. `label` is the chart's description for a screen reader; the data itself is for a keyboard and a screen reader in the list or
 *  table a chart is always shown with, because the marks of a chart are not focusable. The chart is sized by its container
 *  (`.chart-canvas`) and follows it when it changes. It is drawn again from scratch when its option changes and disposed with the
 *  component: replacing the picture is cheap at this size, and an update in place left the old marks in the SVG. There is no animation,
 *  so a drill, a filter or a theme change replaces what was there at once, which is also right for a reader who prefers reduced motion. */
export function Chart({ option, label, onClick }: { option: EChartsCoreOption; label: string; onClick?: (click: ChartClick) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const handler = useRef(onClick);
  handler.current = onClick;

  useEffect(() => {
    const el = box.current!;
    const chart = echarts.init(el, null, { renderer: "svg" });
    chart.on("click", (event) => {
      if (event.componentType === "xAxis" || event.componentType === "yAxis") handler.current?.({ name: String(event.value ?? ""), axis: String(event.value ?? "") });
      else handler.current?.({ name: String(event.name ?? ""), data: event.data });
    });
    // The description is ours, so it replaces the one ECharts would work out from the data.
    chart.setOption({ ...option, animation: false, aria: { enabled: true, label: { description: label } } });
    const watcher = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => chart.resize());
    watcher?.observe(el);
    return () => { watcher?.disconnect(); chart.dispose(); };
  }, [option, label]);

  return <div className="chart-canvas" role="img" ref={box} />;
}

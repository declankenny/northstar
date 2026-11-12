import { TreemapChart } from "echarts/charts";
import { AriaComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

/** The one place ECharts is imported and set up, so only the chart types and components in use are in the bundle: `echarts/core` with
 *  explicit `use`, never the whole library. The SVG renderer, so a chart is DOM that can be styled and tested. A chart type is added here
 *  when the first report uses it, with its own compatibility probe (see Chart.test.tsx). */
echarts.use([TreemapChart, TooltipComponent, AriaComponent, SVGRenderer]);

export { echarts };
export type { EChartsCoreOption, ECharts } from "echarts/core";

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsType } from "echarts/core";
import type { PrometheusSeries } from "@agent-py/api-contracts";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

const props = defineProps<{
  series: readonly PrometheusSeries[];
}>();

const container = ref<HTMLDivElement | null>(null);
let chart: EChartsType | null = null;
let resizeObserver: ResizeObserver | null = null;
let themeObserver: MutationObserver | null = null;

// 品牌紫罗兰打头，其余序列在浅色/深色主题下都有足够对比度。
const PALETTE = ["#7c6bff", "#60a5fa", "#f59e0b", "#f472b6", "#a78bfa", "#34d399"];

// 图表配色跟随主题变量；jsdom 等环境取不到值时回退到浅色主题色。
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined" || typeof document === "undefined") return fallback;
  const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value === "" ? fallback : value;
}

function seriesName(item: PrometheusSeries): string {
  const name = item.metric["__name__"] ?? "series";
  const extra = Object.entries(item.metric)
    .filter(([key]) => key !== "__name__")
    .slice(0, 3)
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
  return extra !== "" ? `${name}{${extra}}` : name;
}

function buildOption(): echarts.EChartsCoreOption {
  const labelColor = cssVar("--text-secondary", "#5a6474");
  const lineColor = cssVar("--line", "#e5e8ee");
  return {
    color: PALETTE,
    backgroundColor: "transparent",
    animation: false,
    grid: { left: 64, right: 24, top: 44, bottom: 40 },
    legend: { top: 4, type: "scroll", textStyle: { color: labelColor } },
    tooltip: {
      trigger: "axis",
      backgroundColor: cssVar("--surface-raised", "#ffffff"),
      borderColor: cssVar("--line-strong", "#ccd2dc"),
      textStyle: { color: cssVar("--text-primary", "#1a1d24") }
    },
    xAxis: {
      type: "time",
      axisLabel: { color: labelColor, hideOverlap: true },
      axisLine: { lineStyle: { color: cssVar("--line-strong", "#ccd2dc") } },
      splitLine: { show: false }
    },
    yAxis: {
      type: "value",
      axisLabel: { color: labelColor },
      splitLine: { lineStyle: { color: lineColor } }
    },
    series: props.series.map((item) => ({
      name: seriesName(item),
      type: "line" as const,
      showSymbol: false,
      data: item.points.map((point) => [point.timestamp, point.value])
    }))
  };
}

function render(): void {
  chart?.setOption(buildOption(), { notMerge: true });
}

onMounted(() => {
  if (container.value === null) return;
  chart = echarts.init(container.value, undefined, { renderer: "svg" });
  render();
  // jsdom 等测试环境没有 ResizeObserver，缺失时跳过自适应。
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => chart?.resize());
    resizeObserver.observe(container.value);
  }
  // 主题切换时重新读取 CSS 变量并重绘。
  if (typeof MutationObserver !== "undefined" && typeof document !== "undefined") {
    themeObserver = new MutationObserver(() => render());
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
});

watch(
  () => props.series,
  () => render(),
  { deep: true }
);

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  themeObserver?.disconnect();
  themeObserver = null;
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div
    ref="container"
    class="metric-chart"
    role="img"
    :aria-label="`指标图表，共 ${props.series.length} 条序列`"
  ></div>
</template>

<style scoped>
.metric-chart {
  width: 100%;
  height: 100%;
  min-height: 320px;
}
</style>

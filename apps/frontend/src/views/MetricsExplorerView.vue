<script setup lang="ts">
import { Activity, RefreshCw, Search, Table2 } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";

import type { PrometheusSeries } from "@agent-py/api-contracts";

import MetricChart from "../components/MetricChart.vue";
import AppEmptyState from "../components/AppEmptyState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import MonitorSubNav from "../components/MonitorSubNav.vue";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "../components/ui";
import { usePrometheusStore } from "../stores/prometheus";

const prometheus = usePrometheusStore();

// 快捷时间范围：1 小时 / 6 小时 / 24 小时 / 3 天（后端上限）。
const RANGES = [
  { label: "近 1 小时", ms: 3_600_000, step: 30 },
  { label: "近 6 小时", ms: 6 * 3_600_000, step: 60 },
  { label: "近 24 小时", ms: 24 * 3_600_000, step: 120 },
  { label: "近 3 天", ms: 3 * 24 * 3_600_000, step: 300 }
] as const;

const query = ref("up");
const selectedMetric = ref("");
const rangeIndex = ref(0);
const ranQuery = ref(false);
// reka-ui Select 不接受空字符串值，用哨兵值表示「手动输入 PromQL」。
const MANUAL_METRIC = "__manual__";

const hasSources = computed(() => prometheus.sources.length > 0);
const metricValue = computed(() => (selectedMetric.value === "" ? MANUAL_METRIC : selectedMetric.value));

onMounted(() => {
  void prometheus
    .initialize()
    .then(() => {
      if (prometheus.selectedId !== null) {
        void prometheus.fetchLabelValues("__name__").catch(() => undefined);
      }
    })
    .catch(() => undefined);
});

function onSourceChange(value: unknown): void {
  if (typeof value !== "string" || value === "") return;
  prometheus.select(value);
  ranQuery.value = false;
  void prometheus.fetchLabelValues("__name__").catch(() => undefined);
}

function onMetricChange(value: unknown): void {
  const name = typeof value === "string" && value !== MANUAL_METRIC ? value : "";
  selectedMetric.value = name;
  if (name !== "") query.value = name;
}

function onRangeChange(value: unknown): void {
  const index = typeof value === "string" ? Number(value) : Number.NaN;
  if (Number.isInteger(index) && RANGES[index] !== undefined) rangeIndex.value = index;
}

function run(operation: () => Promise<void>): void {
  void operation()
    .then(() => { ranQuery.value = true; })
    .catch(() => undefined);
}

function execute(): void {
  const range = RANGES[rangeIndex.value] ?? RANGES[0]!;
  const endMs = Date.now();
  run(() =>
    prometheus.queryRange({
      query: query.value.trim(),
      startMs: endMs - range.ms,
      endMs,
      stepSeconds: range.step
    })
  );
}

function formatSeriesName(item: PrometheusSeries): string {
  const name = item.metric["__name__"] ?? "series";
  const extra = Object.entries(item.metric)
    .filter(([key]) => key !== "__name__")
    .slice(0, 4)
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
  return extra !== "" ? `${name}{${extra}}` : name;
}

function latestValue(item: PrometheusSeries): string {
  const last = item.points[item.points.length - 1];
  return last === undefined ? "-" : String(last.value);
}
</script>

<template>
  <section class="metrics-view" aria-label="Prometheus 指标监控">
    <MonitorSubNav />
    <header class="metrics-view__header">
      <div><p>监控中心</p><h2>Prometheus 指标监控</h2><span>选择你接入的 Prometheus 数据源，查看有哪些指标、执行 PromQL 查询并绘制真实时序图。</span></div>
    </header>
    <AppLoadingState v-if="prometheus.isLoading" label="正在加载数据源" />
    <div v-else-if="!hasSources" class="metrics-view__empty-block">
      <AppEmptyState
        action-label="去配置数据源"
        action-to="/monitor/sources"
        detail="在「数据源管理」中填写 Prometheus 地址并检查连接，之后就能在这里选择真实指标、执行 PromQL 查询。"
        title="还没有接入 Prometheus 数据源"
      />
    </div>
    <div v-else class="metrics-view__body">
      <form class="metrics-view__querybar" @submit.prevent="execute">
        <div class="metrics-view__field"><span>数据源</span>
          <Select :model-value="prometheus.selectedId ?? ''" @update:model-value="onSourceChange">
            <SelectTrigger class="metrics-view__select" aria-label="数据源"><SelectValue placeholder="选择数据源" /></SelectTrigger>
            <SelectContent>
              <SelectItem v-for="source in prometheus.sources" :key="source.id" :value="source.id">{{ source.name }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="metrics-view__field"><span>指标</span>
          <Select :model-value="metricValue" @update:model-value="onMetricChange">
            <SelectTrigger class="metrics-view__select" aria-label="指标"><SelectValue placeholder="选择指标" /></SelectTrigger>
            <SelectContent>
              <SelectItem :value="MANUAL_METRIC">（手动输入 PromQL）</SelectItem>
              <SelectItem v-for="name in prometheus.metricNames" :key="name" :value="name">{{ name }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <label class="metrics-view__promql"><span>PromQL</span>
          <input v-model.trim="query" type="text" required maxlength="4000" placeholder="up / rate(http_requests_total[5m])" />
        </label>
        <div class="metrics-view__field"><span>范围</span>
          <Select :model-value="String(rangeIndex)" @update:model-value="onRangeChange">
            <SelectTrigger class="metrics-view__select" aria-label="时间范围"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem v-for="(range, index) in RANGES" :key="range.label" :value="String(index)">{{ range.label }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <button type="submit" class="metrics-view__run" :disabled="prometheus.isLoadingQuery"><RefreshCw :size="15" :class="{ spin: prometheus.isLoadingQuery }" aria-hidden="true" />{{ prometheus.isLoadingQuery ? '查询中' : '查询' }}</button>
      </form>

      <section v-if="prometheus.isLoadingQuery" class="metrics-view__chart">
        <AppLoadingState label="正在查询指标序列" />
      </section>
      <section v-else-if="prometheus.series.length > 0" class="metrics-view__chart" aria-label="指标时序图">
        <MetricChart :series="prometheus.series" />
      </section>
      <div v-else class="metrics-view__empty-block">
        <AppEmptyState
          :detail="ranQuery ? '请检查 PromQL 语法、指标名或时间范围后重试。' : '选择数据源与指标，或直接输入 PromQL，点击查询后会绘制真实的时序图。'"
          :title="ranQuery ? '查询没有返回序列' : '还没有查询结果'"
        />
      </div>

      <section v-if="prometheus.series.length > 0 && !prometheus.isLoadingQuery" class="metrics-view__table" aria-label="序列明细">
        <header><Table2 :size="15" aria-hidden="true" /><h3>序列明细（{{ prometheus.series.length }} 条）</h3></header>
        <div class="metrics-view__scroll">
          <Table>
            <TableHeader>
              <TableRow><TableHead>序列</TableHead><TableHead>点数</TableHead><TableHead>最新值</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="(item, index) in prometheus.series" :key="index">
                <TableCell class="metrics-view__mono">{{ formatSeriesName(item) }}</TableCell>
                <TableCell>{{ item.points.length }}</TableCell>
                <TableCell class="metrics-view__mono">{{ latestValue(item) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.metrics-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; }
.metrics-view__header { border-bottom: 1px solid var(--line); padding: 0.85rem clamp(1rem, 3vw, 2rem); }
.metrics-view__header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 600; margin: 0 0 0.25rem; }
.metrics-view__header h2 { font-size: 1.05rem; margin: 0; }
.metrics-view__header span { color: var(--text-secondary); display: block; font-size: 0.78rem; margin-top: 0.3rem; }
.metrics-view__body { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 0; min-height: 0; overflow-y: auto; }
.metrics-view__querybar { align-items: end; border-bottom: 1px solid var(--line); display: grid; gap: 0.7rem; grid-template-columns: minmax(9rem, 12rem) minmax(12rem, 16rem) minmax(0, 1fr) minmax(7rem, 9rem) auto; padding: 0.9rem clamp(1rem, 3vw, 2rem); }
.metrics-view__querybar label, .metrics-view__field { color: var(--text-secondary); display: grid; font-size: 0.72rem; font-weight: 600; gap: 0.3rem; min-width: 0; }
.metrics-view__querybar select, .metrics-view__querybar input { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 0.4rem; color: var(--text-primary); font: inherit; min-height: 2.05rem; min-width: 0; padding: 0 0.6rem; width: 100%; }
.metrics-view__select { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 0.4rem; color: var(--text-primary); font-size: 0.78rem; font-weight: 400; min-height: 2.05rem; padding: 0 0.55rem; width: 100%; }
.metrics-view__select svg { color: var(--text-tertiary); opacity: 1; }
.metrics-view__run { align-items: center; background: var(--accent-solid); border: 1px solid var(--accent-solid); border-radius: 0.4rem; color: white; display: inline-flex; font-size: 0.78rem; font-weight: 600; gap: 0.35rem; justify-content: center; min-height: 2.05rem; padding: 0 0.9rem; }
.metrics-view__chart { background: var(--surface); border-bottom: 1px solid var(--line); height: clamp(20rem, 40vh, 26rem); padding: 0.75rem clamp(1rem, 3vw, 2rem) 1rem; }
.metrics-view__table { padding: 0.9rem clamp(1rem, 3vw, 2rem) 1.4rem; }
.metrics-view__table header { align-items: center; color: var(--text-secondary); display: flex; gap: 0.4rem; }
.metrics-view__table h3 { font-size: 0.82rem; margin: 0; }
.metrics-view__scroll { max-height: 16rem; margin-top: 0.6rem; overflow-y: auto; }
.metrics-view__table table { border-collapse: collapse; font-size: 0.76rem; width: 100%; }
.metrics-view__table th, .metrics-view__table td { border-bottom: 1px solid var(--line); padding: 0.5rem 0.6rem; text-align: left; }
.metrics-view__table th { color: var(--text-tertiary); font-size: 0.68rem; font-weight: 600; }
.metrics-view__mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; overflow-wrap: anywhere; }
.metrics-view__empty-block { padding: 1.5rem clamp(1rem, 3vw, 2rem) 2rem; }
.metrics-view__empty-block .empty-state { border-top: 0; }
.spin { animation: spin 0.8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .metrics-view__querybar { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .metrics-view__promql { grid-column: 1 / -1; } }
@media (max-width: 760px) { .metrics-view { height: auto; } .metrics-view__body { grid-template-rows: none; } .metrics-view__querybar { grid-template-columns: minmax(0, 1fr); } .metrics-view__chart { height: 18rem; } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>

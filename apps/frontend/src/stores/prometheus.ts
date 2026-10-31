import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  PrometheusSeries,
  PrometheusSource,
  PrometheusSourceMutationRequest
} from "@agent-py/api-contracts";

import {
  createPrometheusClient,
  type PrometheusClient
} from "../prometheus/prometheusClient";
import { toUserFacingError } from "../ui/userFacingError";
import { useFeedbackStore } from "./feedback";

let clientFactory: () => PrometheusClient = createPrometheusClient;

export function setPrometheusClientFactoryForTests(
  factory: (() => PrometheusClient) | null
): void {
  clientFactory = factory ?? createPrometheusClient;
}

export const usePrometheusStore = defineStore("prometheus", () => {
  const client = clientFactory();
  const sources = ref<readonly PrometheusSource[]>([]);
  const selectedId = ref<string | null>(null);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const checkingId = ref<string | null>(null);

  // 指标浏览器状态：标签值缓存（__name__ 即指标名）、查询结果。
  const labelValues = ref<Record<string, readonly string[]>>({});
  const isLoadingLabels = ref(false);
  const series = ref<readonly PrometheusSeries[]>([]);
  const isLoadingQuery = ref(false);

  const selected = computed(
    () => sources.value.find((item) => item.id === selectedId.value) ?? null
  );
  const metricNames = computed(() => labelValues.value["__name__"] ?? []);

  function report(error: unknown): void {
    useFeedbackStore().showError(toUserFacingError(error));
  }

  function upsert(source: PrometheusSource): void {
    sources.value = [
      ...sources.value.filter((item) => item.id !== source.id),
      source
    ];
    selectedId.value = source.id;
  }

  async function initialize(): Promise<void> {
    isLoading.value = true;
    try {
      const response = await client.list();
      sources.value = response.items;
      selectedId.value ??= response.items[0]?.id ?? null;
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  async function create(request: PrometheusSourceMutationRequest): Promise<void> {
    isSaving.value = true;
    try {
      upsert(await client.create(request));
      useFeedbackStore().show("success", "Prometheus 数据源已创建");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function update(request: PrometheusSourceMutationRequest): Promise<void> {
    if (selectedId.value === null) return;
    isSaving.value = true;
    try {
      upsert(await client.update(selectedId.value, request));
      useFeedbackStore().show("success", "Prometheus 数据源已保存");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function check(sourceId: string): Promise<void> {
    checkingId.value = sourceId;
    try {
      const response = await client.check(sourceId);
      upsert(response.source);
      useFeedbackStore().show(
        response.check.ok ? "success" : "error",
        response.check.ok ? "数据源连接正常" : response.check.error ?? "数据源检查失败"
      );
    } catch (error) {
      report(error);
      throw error;
    } finally {
      checkingId.value = null;
    }
  }

  async function remove(sourceId: string): Promise<void> {
    isSaving.value = true;
    try {
      await client.delete(sourceId);
      sources.value = sources.value.filter((item) => item.id !== sourceId);
      selectedId.value = sources.value[0]?.id ?? null;
      useFeedbackStore().show("success", "Prometheus 数据源已删除");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchLabelValues(label: string): Promise<void> {
    if (selectedId.value === null || labelValues.value[label] !== undefined) return;
    isLoadingLabels.value = true;
    try {
      const response = await client.labelValues(selectedId.value, label);
      labelValues.value = { ...labelValues.value, [label]: response.values };
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoadingLabels.value = false;
    }
  }

  function applySeries(next: readonly PrometheusSeries[]): void {
    series.value = next;
  }

  async function queryRange(request: {
    query: string;
    startMs: number;
    endMs: number;
    stepSeconds: number;
  }): Promise<void> {
    if (selectedId.value === null) return;
    isLoadingQuery.value = true;
    try {
      const response = await client.queryRange({
        sourceId: selectedId.value,
        ...request
      });
      series.value = response.series;
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoadingQuery.value = false;
    }
  }

  async function queryInstant(request: { query: string; timeMs?: number }): Promise<void> {
    if (selectedId.value === null) return;
    isLoadingQuery.value = true;
    try {
      const response = await client.query({ sourceId: selectedId.value, ...request });
      series.value = response.series;
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoadingQuery.value = false;
    }
  }

  function clearSeries(): void {
    series.value = [];
  }

  return {
    checkingId,
    clearSeries,
    fetchLabelValues,
    isLoading,
    isLoadingLabels,
    isLoadingQuery,
    isSaving,
    labelValues,
    metricNames,
    queryInstant,
    queryRange,
    remove,
    series,
    sources,
    selected,
    selectedId,
    check,
    create,
    initialize,
    select: (sourceId: string) => {
      selectedId.value = sourceId;
      labelValues.value = {};
      clearSeries();
    },
    update
  };
});

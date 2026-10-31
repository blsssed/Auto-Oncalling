import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  PrometheusSeries,
  PrometheusSource
} from "@agent-py/api-contracts";
import type { PrometheusClient } from "../src/prometheus/prometheusClient";
import {
  setPrometheusClientFactoryForTests,
  usePrometheusStore
} from "../src/stores/prometheus";

const source = (overrides: Partial<PrometheusSource> = {}): PrometheusSource => ({
  id: "prom_1",
  ownerUserId: "user_1",
  name: "本机 Prometheus",
  baseUrl: "http://127.0.0.1:9090",
  username: null,
  enabled: true,
  timeoutSeconds: 10,
  maxSeries: 20,
  lastCheck: null,
  createdAt: "2026-10-29T00:00:00.000Z",
  updatedAt: "2026-10-29T00:00:00.000Z",
  ...overrides
});

const series = (overrides: Partial<PrometheusSeries> = {}): PrometheusSeries => ({
  metric: { __name__: "up", job: "demo" },
  points: [
    { timestamp: 1_700_000_000_000, value: 1 },
    { timestamp: 1_700_000_060_000, value: 0 }
  ],
  ...overrides
});

function fakeClient(overrides: Partial<PrometheusClient> = {}): PrometheusClient {
  return {
    list: vi.fn().mockResolvedValue({ items: [source()] }),
    create: vi.fn().mockImplementation(async (request) =>
      source({ id: "prom_new", name: request.name, baseUrl: request.baseUrl })
    ),
    update: vi.fn().mockImplementation(async (_sourceId, request) =>
      source({ name: request.name, baseUrl: request.baseUrl })
    ),
    delete: vi.fn().mockResolvedValue({ deleted: true, sourceId: "prom_1" }),
    check: vi.fn().mockResolvedValue({
      source: source({ lastCheck: { ok: true, error: null, checkedAt: "2026-10-29T00:01:00.000Z" } }),
      check: { ok: true, error: null, checkedAt: "2026-10-29T00:01:00.000Z" }
    }),
    labelValues: vi
      .fn()
      .mockResolvedValue({ label: "__name__", values: ["up", "process_cpu_seconds_total"] }),
    query: vi.fn().mockResolvedValue({ query: "up", series: [series()] }),
    queryRange: vi.fn().mockResolvedValue({
      query: "up",
      startMs: 1_700_000_000_000,
      endMs: 1_700_003_600_000,
      stepSeconds: 30,
      series: [series()]
    }),
    ...overrides
  };
}

afterEach(() => {
  setPrometheusClientFactoryForTests(null);
});

describe("prometheus store", () => {
  it("loads sources and selects the first one on initialize", async () => {
    setPrometheusClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = usePrometheusStore();

    await store.initialize();

    expect(store.sources).toHaveLength(1);
    expect(store.selectedId).toBe("prom_1");
    expect(store.selected?.name).toBe("本机 Prometheus");
  });

  it("runs range queries against the selected source and keeps series", async () => {
    const client = fakeClient();
    setPrometheusClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = usePrometheusStore();
    await store.initialize();

    await store.queryRange({
      query: "up",
      startMs: 1_700_000_000_000,
      endMs: 1_700_003_600_000,
      stepSeconds: 30
    });

    expect(client.queryRange).toHaveBeenCalledWith({
      sourceId: "prom_1",
      query: "up",
      startMs: 1_700_000_000_000,
      endMs: 1_700_003_600_000,
      stepSeconds: 30
    });
    expect(store.series).toHaveLength(1);
  });

  it("caches metric label values per source and resets on source switch", async () => {
    const client = fakeClient();
    setPrometheusClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = usePrometheusStore();
    await store.initialize();

    await store.fetchLabelValues("__name__");
    await store.fetchLabelValues("__name__");

    expect(client.labelValues).toHaveBeenCalledTimes(1);
    expect(store.metricNames).toContain("up");

    store.select("prom_2");
    expect(store.metricNames).toHaveLength(0);
    expect(store.series).toHaveLength(0);
  });

  it("upserts sources after create, check, and delete", async () => {
    const client = fakeClient();
    setPrometheusClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = usePrometheusStore();
    await store.initialize();

    await store.create({ name: "生产", baseUrl: "https://prom.example.com" });
    expect(store.sources.map((item) => item.id)).toContain("prom_new");
    expect(store.selectedId).toBe("prom_new");

    await store.check("prom_new");
    expect(store.selected?.lastCheck?.ok).toBe(true);

    await store.remove("prom_new");
    expect(store.sources.map((item) => item.id)).not.toContain("prom_new");
  });
});

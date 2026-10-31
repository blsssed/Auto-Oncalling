// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { Router } from "vue-router";

import MetricChart from "../src/components/MetricChart.vue";
import MonitorSubNav from "../src/components/MonitorSubNav.vue";
import { createAppRouter } from "../src/router";
import type { PrometheusSeries } from "@agent-py/api-contracts";

const series: PrometheusSeries[] = [
  {
    metric: { __name__: "up", job: "demo" },
    points: [
      { timestamp: 1_700_000_000_000, value: 1 },
      { timestamp: 1_700_000_060_000, value: 0 }
    ]
  }
];

describe("prometheus components", () => {
  it("renders an accessible metric chart placeholder and disposes cleanly", () => {
    const wrapper = mount(MetricChart, { props: { series } });

    const container = wrapper.get("[role=img]");
    expect(container.attributes("aria-label")).toContain("1 条序列");
    expect(container.classes()).toContain("metric-chart");
    wrapper.unmount();
  });

  it("renders empty state gracefully without any series", () => {
    const wrapper = mount(MetricChart, { props: { series: [] } });

    expect(wrapper.get("[role=img]").attributes("aria-label")).toContain("0 条序列");
    wrapper.unmount();
  });

  it("highlights the active monitor tab from the current route", async () => {
    const router: Router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });
    await router.push("/monitor/sources");
    await router.isReady();

    const wrapper = mount(MonitorSubNav, { global: { plugins: [router] } });

    const links = wrapper.findAll("a");
    expect(links.map((link) => link.text())).toEqual(["Prometheus 指标监控", "数据源管理"]);
    expect(links[0]?.attributes("href")).toBe("/monitor/metrics");
    expect(links[1]?.attributes("href")).toBe("/monitor/sources");
    expect(wrapper.get('[aria-current="page"]').text()).toBe("数据源管理");
  });
});

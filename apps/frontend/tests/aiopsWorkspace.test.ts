// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { Router } from "vue-router";

import AiopsSubNav from "../src/components/AiopsSubNav.vue";
import { createAppRouter } from "../src/router";

function createRouter(): Router {
  return createAppRouter({
    initialize: vi.fn().mockResolvedValue(undefined),
    isAuthenticated: () => true
  });
}

describe("aiops workspace navigation", () => {
  it("renders five always-visible tabs with full workspace links", async () => {
    const router = createRouter();
    await router.push("/aiops/overview");
    await router.isReady();

    const wrapper = mount(AiopsSubNav, { global: { plugins: [router] } });
    const links = wrapper.findAll("a");

    expect(wrapper.attributes("aria-label")).toBe("AI 运维中心导航");
    expect(links.map((link) => link.text())).toEqual(["总览", "诊断", "告警", "案例", "历史"]);
    expect(links.map((link) => link.attributes("href"))).toEqual([
      "/aiops/overview",
      "/aiops",
      "/aiops/alerts",
      "/aiops/cases",
      "/aiops/history"
    ]);
    expect(wrapper.get('[aria-current="page"]').text()).toBe("总览");
  });

  it("highlights exactly one tab across the workspace routes", async () => {
    for (const [path, label] of [
      ["/aiops", "诊断"],
      ["/aiops/alerts", "告警"],
      ["/aiops/cases", "案例"],
      ["/aiops/history", "历史"]
    ] as const) {
      const router = createRouter();
      await router.push(path);
      await router.isReady();

      const wrapper = mount(AiopsSubNav, { global: { plugins: [router] } });
      const active = wrapper.findAll(".aiops-sub-nav__link--active");
      expect(active).toHaveLength(1);
      expect(active[0]!.text()).toBe(label);
      expect(wrapper.get('[aria-current="page"]').text()).toBe(label);
    }
  });
});

import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import { createAppRouter } from "../src/router";
import { useFeedbackStore } from "../src/stores/feedback";

describe("application shell router", () => {
  it("redirects anonymous visitors to sign in and preserves the target route", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => false
    });

    await router.push("/knowledge");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/knowledge");
  });

  it("redirects authenticated visitors away from public auth routes", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    await router.push("/register");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/aiops");
  });

  it("resolves the split aiops sub routes for authenticated visitors", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    for (const [path, name] of [
      ["/aiops", "aiops"],
      ["/aiops/overview", "aiops-overview"],
      ["/aiops/alerts", "aiops-alerts"],
      ["/aiops/cases", "aiops-cases"],
      ["/aiops/history", "aiops-history"]
    ] as const) {
      await router.push(path);
      await router.isReady();
      expect(router.currentRoute.value.name).toBe(name);
      expect(router.currentRoute.value.meta.title).toBeTruthy();
    }
  });

  it("resolves the monitor center routes for authenticated visitors", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    for (const [path, name, title] of [
      ["/monitor/metrics", "monitor-metrics", "Prometheus 指标监控"],
      ["/monitor/sources", "monitor-sources", "数据源管理"]
    ] as const) {
      await router.push(path);
      await router.isReady();
      expect(router.currentRoute.value.name).toBe(name);
      expect(router.currentRoute.value.meta.title).toBe(title);
    }
  });

  it("resolves the profile center routes for authenticated visitors", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    await router.push("/profile");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/profile/model");

    for (const [path, name, title] of [
      ["/profile/model", "profile-model", "模型配置"],
      ["/profile/info", "profile-info", "个人信息"],
      ["/profile/about", "profile-about", "关于"]
    ] as const) {
      await router.push(path);
      await router.isReady();
      expect(router.currentRoute.value.name).toBe(name);
      expect(router.currentRoute.value.meta.title).toBe(title);
    }
  });

  it("redirects anonymous visitors away from the profile center", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => false
    });

    await router.push("/profile/info");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/profile/info");
  });

  it("holds dismissible normalized feedback in application state", () => {
    setActivePinia(createPinia());
    const feedback = useFeedbackStore();

    feedback.showError("The system is temporarily unavailable.");
    expect(feedback.current?.message).toBe("The system is temporarily unavailable.");

    feedback.dismiss();
    expect(feedback.current).toBeNull();
  });
});

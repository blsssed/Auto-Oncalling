// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Router } from "vue-router";

import type { ActiveAlert, AiopsDiagnosticCase, AiopsDiagnosticEvidenceChain, AiopsDiagnosticSummary, SseEvent } from "@agent-py/api-contracts";

import type { AiopsClient } from "../src/aiops/aiopsClient";
import { createAppRouter } from "../src/router";
import { setAiopsClientFactoryForTests } from "../src/stores/aiops";
import AiopsAlertsView from "../src/views/AiopsAlertsView.vue";
import AiopsCasesView from "../src/views/AiopsCasesView.vue";
import AiopsHistoryView from "../src/views/AiopsHistoryView.vue";

const alert: ActiveAlert = {
  id: "fingerprint-checkout-latency",
  source: "local-alertmanager",
  alertName: "CheckoutLatencyHigh",
  service: "checkout",
  severity: "critical",
  status: "active",
  startsAt: "2026-07-10T08:00:00Z",
  summary: "Checkout latency is above the SLO.",
  labels: { alertname: "CheckoutLatencyHigh", service: "checkout" },
  annotations: { summary: "Checkout latency is above the SLO." },
  context: { fingerprint: "fingerprint-checkout-latency" }
};

const task: AiopsDiagnosticSummary = {
  id: "diagnostic_1", ownerUserId: "user_1", status: "succeeded", query: "Inspect latency", inputPayload: {}, resultPayload: {}, createdAt: "2026-07-10T08:00:00Z", updatedAt: "2026-07-10T08:00:02Z", completedAt: "2026-07-10T08:00:02Z", reports: []
};

const diagnosticCase: AiopsDiagnosticCase = {
  id: "case_1", ownerUserId: "user_1", taskId: "diagnostic_1", reportId: "report_1", documentId: "doc_1", indexTaskId: "index_1", alertName: "CheckoutLatencyHigh", service: "checkout", keywords: ["checkout"], rootCause: "", remediation: "", summary: "案例摘要", evidenceIds: [], createdAt: "2026-07-10T08:00:00Z"
};

afterEach(() => setAiopsClientFactoryForTests(null));

function fakeClient(): AiopsClient {
  const chain: AiopsDiagnosticEvidenceChain = { task, steps: [], toolCalls: [], evidence: [], reports: [], reportEvidenceLinks: [], checkpoints: [] };
  return {
    createDiagnostic: async () => task,
    getEvidenceChain: async () => chain,
    listActiveAlerts: async () => ({ items: [alert] }),
    listDiagnosticCases: async () => ({ items: [diagnosticCase] }),
    listDiagnostics: async () => ({ items: [task] }),
    saveDiagnosticCase: async () => { throw new Error("not used"); },
    streamDiagnostic: async function* (): AsyncIterable<SseEvent> { yield { id: "complete", type: "complete", channel: "aiops", timestamp: "2026-07-10T08:00:02Z" }; }
  };
}

async function mountView(view: typeof AiopsAlertsView | typeof AiopsCasesView | typeof AiopsHistoryView): Promise<{ wrapper: ReturnType<typeof mount>; router: Router }> {
  setAiopsClientFactoryForTests(() => fakeClient());
  setActivePinia(createPinia());
  const router = createAppRouter({
    initialize: vi.fn().mockResolvedValue(undefined),
    isAuthenticated: () => true
  });
  const wrapper = mount(view, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("aiops sub views", () => {
  it("renders real alerts in the workspace and routes to the console on diagnose", async () => {
    const { wrapper, router } = await mountView(AiopsAlertsView);

    expect(wrapper.text()).toContain("CheckoutLatencyHigh");
    await wrapper.get('button[aria-label="诊断 CheckoutLatencyHigh"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/aiops");
  });

  it("renders the case library and opens the console when a case is selected", async () => {
    const { wrapper, router } = await mountView(AiopsCasesView);

    expect(wrapper.text()).toContain("CheckoutLatencyHigh");
    expect(wrapper.text()).toContain("案例摘要");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/aiops");
  });

  it("renders diagnostic history tasks", async () => {
    const { wrapper } = await mountView(AiopsHistoryView);

    expect(wrapper.text()).toContain("Inspect latency");
  });
});

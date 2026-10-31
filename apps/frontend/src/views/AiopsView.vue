<script setup lang="ts">
import { computed, ref, nextTick, onMounted } from "vue";

import { Activity, FileSearch, Wrench, Zap } from "lucide-vue-next";

import AiopsEvidenceChain from "../components/AiopsEvidenceChain.vue";
import AiopsRunForm from "../components/AiopsRunForm.vue";
import AiopsReportPanel, { type AiopsReportDisplay } from "../components/AiopsReportPanel.vue";
import AiopsTimeline from "../components/AiopsTimeline.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import AsyncStatusBadge from "../components/AsyncStatusBadge.vue";
import { useAiopsStore } from "../stores/aiops";

import type { AiopsDiagnosticScope, ConfirmAiopsDiagnosticCaseRequest } from "@agent-py/api-contracts";
const aiops = useAiopsStore();
const evidenceOpen = ref(false);
const confirming = ref(false);
const confirmed = computed(() => aiops.diagnosticCases.some(c => c.taskId === aiops.activeDiagnosticId && c.reviewStatus === "confirmed"));
async function locateEvidence(id: string): Promise<void> {
  evidenceOpen.value = true;
  await nextTick();
  const target = document.getElementById(`evidence-${id}`);
  if (target instanceof HTMLDetailsElement) target.open = true;
  target?.scrollIntoView({ block: "center", behavior: "auto" });
}
async function confirmCase(body: ConfirmAiopsDiagnosticCaseRequest): Promise<void> {
  confirming.value = true;
  try { await aiops.saveActiveCase(body); } finally { confirming.value = false; }
}
const activeTitle = computed(() => aiops.activeTask?.query ?? "智能诊断工作区");
const activeStatus = computed(() => (aiops.isRunning ? "running" : aiops.activeTask?.status ?? "ready"));
const evidenceCount = computed(() => aiops.evidenceChain?.evidence.length ?? 0);
const toolCallCount = computed(() => aiops.evidenceChain?.toolCalls.length ?? 0);
const isEffectivelyRunning = computed(
  () => aiops.isRunning || aiops.activeTask?.status === "running"
);
const activeReport = computed<AiopsReportDisplay | null>(() => {
  const reports = aiops.evidenceChain?.reports ?? [];
  if (reports.length > 0) {
    const report = reports[reports.length - 1];
    if (report) return report;
  }
  for (let index = aiops.liveEvents.length - 1; index >= 0; index -= 1) {
    const event = aiops.liveEvents[index];
    if (event?.type === "report") {
      return { ...event.report, createdAt: event.timestamp };
    }
  }
  return null;
});
const lifecycleText = computed(() => {
  if (isEffectivelyRunning.value) return "执行中";
  if (aiops.activeTask?.status === "accepted") return "等待中";
  if (aiops.activeTask?.status === "failed") return "失败";
  if (aiops.activeTask?.status === "succeeded") return "已完成";
  return "已就绪";
});

onMounted(() => {
  void aiops.initialize().catch(() => undefined);
  aiops.subscribeActiveAlerts();
});

function run(operation: () => Promise<unknown>): void {
  void operation().catch(() => undefined);
}

function startDiagnostic(query: string, alert: Record<string, unknown> | undefined, scope: AiopsDiagnosticScope): void {
  run(() => aiops.runDiagnostic(query, alert, scope));
}
</script>

<template>
  <section class="aiops-view" aria-label="智能诊断工作区">
    <header class="aiops-view__hero">
      <div class="aiops-view__pulse" aria-hidden="true"><span /><span /><span /></div>
      <div>
        <p>Auto Oncall · 证据驱动的值班调查</p>
        <h2>{{ activeTitle }}</h2>
      </div>
      <AsyncStatusBadge :status="activeStatus" :detail="lifecycleText" />
    </header>

    <AppLoadingState v-if="aiops.isLoading && aiops.history.length === 0" label="正在加载诊断历史" />
    <AppErrorState v-else-if="aiops.errorMessage && aiops.history.length === 0" :can-retry="true" :message="aiops.errorMessage" @retry="run(aiops.initialize)" />
    <div v-else class="aiops-view__workspace">
      <div class="aiops-view__console">
        <aside class="aiops-view__left" aria-label="诊断输入">
          <AiopsRunForm :disabled="aiops.isLoading" :is-running="aiops.isRunning" @cancel="run(aiops.cancelActive)" @run="startDiagnostic" />
        </aside>

        <main class="aiops-view__center" aria-label="实时诊断">
          <section class="aiops-view__status-strip" aria-label="诊断状态概览">
            <div><span><Activity :size="13" aria-hidden="true" />当前状态</span><strong>{{ lifecycleText }}</strong></div>
            <div><span><Zap :size="13" aria-hidden="true" />实时事件</span><strong>{{ aiops.liveEvents.length }}</strong></div>
            <div><span><FileSearch :size="13" aria-hidden="true" />证据</span><strong>{{ evidenceCount }}</strong></div>
            <div><span><Wrench :size="13" aria-hidden="true" />工具调用</span><strong>{{ toolCallCount }}</strong></div>
          </section>
          <AiopsReportPanel
            :has-task="aiops.activeTask !== null"
            :is-running="isEffectivelyRunning"
            :report="activeReport"
            :task-failed="aiops.activeTask?.status === 'failed'"
            :confirmed="confirmed" :confirming="confirming"
            @citation="locateEvidence" @confirm="body => run(() => confirmCase(body))"
          />
          <details :open="evidenceOpen" class="investigation-process" @toggle="evidenceOpen = ($event.target as HTMLDetailsElement).open">
            <summary>调查过程与证据 · {{ evidenceCount }} 条证据 / {{ toolCallCount }} 次工具调用</summary>
            <AiopsEvidenceChain :chain="aiops.evidenceChain" />
            <AiopsTimeline :events="aiops.liveEvents" :is-running="isEffectivelyRunning" />
          </details>
        </main>
      </div>
    </div>
  </section>
</template>

<style scoped>
.aiops-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-view__hero { align-items: center; border-bottom: 1px solid var(--line); display: grid; gap: 0.9rem; grid-template-columns: auto minmax(0, 1fr) auto; min-height: 4.6rem; padding: 0.85rem clamp(1rem, 2.6vw, 1.8rem); }
.aiops-view__hero p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 600; margin: 0 0 0.22rem; }
.aiops-view__hero h2 { font-size: clamp(0.98rem, 1.2vw, 1.15rem); font-weight: 600; letter-spacing: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aiops-view__pulse { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 0.5rem; display: inline-flex; gap: 0.22rem; height: 2.45rem; justify-content: center; width: 2.45rem; }
.aiops-view__pulse span { animation: aiops-pulse 1.1s ease-in-out infinite; background: var(--accent); border-radius: 999px; display: block; height: 0.38rem; opacity: 0.35; width: 0.38rem; }
.aiops-view__pulse span:nth-child(2) { animation-delay: 120ms; }
.aiops-view__pulse span:nth-child(3) { animation-delay: 240ms; }
.aiops-view__workspace { display: grid; grid-template-rows: minmax(0, 1fr); min-height: 0; overflow: hidden; }
.aiops-view__console { display: grid; grid-template-columns: minmax(17rem, 0.5fr) minmax(0, 1fr); min-height: 0; overflow: hidden; }
.aiops-view__left, .aiops-view__center { min-height: 0; min-width: 0; }
.aiops-view__left { border-right: 1px solid var(--line); overflow: auto; overscroll-behavior: contain; }
.aiops-view__center { background: var(--surface); border-right: 0; display: grid; grid-template-rows: auto auto auto; align-content: start; overflow: auto; }
.aiops-view__status-strip { border-bottom: 1px solid var(--line); display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.aiops-view__status-strip div { border-right: 1px solid var(--line); display: grid; gap: 0.22rem; min-height: 4.1rem; padding: 0.75rem 0.9rem; }
.aiops-view__status-strip div:last-child { border-right: 0; }
.aiops-view__status-strip span { align-items: center; color: var(--text-tertiary); display: inline-flex; font-size: 0.7rem; font-weight: 600; gap: 0.32rem; }
.aiops-view__status-strip strong { color: var(--text-primary); font-family: var(--font-mono); font-size: 0.96rem; font-weight: 600; }
.investigation-process > summary { padding: 1rem; cursor: pointer; font-size: .8rem; border-bottom: 1px solid var(--line); }
@keyframes aiops-pulse { 0%, 100% { opacity: 0.28; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-0.18rem); } }
@media (prefers-reduced-motion: reduce) { .aiops-view__pulse span { animation: none; } }
@media (max-width: 860px) { .aiops-view { min-height: auto; height: auto; overflow: visible; } .aiops-view__workspace { overflow: visible; } .aiops-view__console { overflow: visible; grid-template-rows: auto; grid-template-columns: minmax(0, 1fr); } .aiops-view__center { overflow: visible; } .aiops-view__hero { grid-template-columns: auto minmax(0, 1fr); } .aiops-view__hero .async-status-badge { grid-column: 1 / -1; justify-self: start; } .aiops-view__left { border-right: 0; border-bottom: 1px solid var(--line); } .aiops-view__status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } .aiops-view__status-strip div:nth-child(2n) { border-right: 0; } }
</style>

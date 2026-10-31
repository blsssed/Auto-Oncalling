<script setup lang="ts">
import { Activity, BellRing, BookOpenCheck, History, Radar, Stethoscope } from "lucide-vue-next";
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

import type { ActiveAlert } from "@agent-py/api-contracts";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AiopsCaseLibrary from "../components/AiopsCaseLibrary.vue";
import AiopsHistory from "../components/AiopsHistory.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import AsyncStatusBadge from "../components/AsyncStatusBadge.vue";
import { useAiopsStore } from "../stores/aiops";

const aiops = useAiopsStore();
const router = useRouter();

const recentAlerts = computed(() => aiops.activeAlerts.slice(0, 5));
const recentHistory = computed(() => aiops.history.slice(0, 5));
const recentCases = computed(() => aiops.diagnosticCases.slice(0, 5));
const criticalCount = computed(
  () => aiops.activeAlerts.filter((alert) => alert.severity.toLowerCase() === "critical").length
);
const alertSummary = computed(() => {
  if (aiops.activeAlerts.length === 0) return "当前没有活跃告警";
  return `严重 ${criticalCount.value} 条，其余 ${aiops.activeAlerts.length - criticalCount.value} 条`;
});
const activeQuery = computed(() => aiops.activeTask?.query ?? "尚未发起诊断");
const activeStatus = computed(() => {
  if (aiops.isRunning) return "running";
  return aiops.activeTask?.status ?? "ready";
});

onMounted(() => {
  void aiops.initialize().catch(() => undefined);
  aiops.subscribeActiveAlerts();
});

function run(operation: () => Promise<unknown>): void {
  void operation().catch(() => undefined);
}

function refreshAlerts(): void {
  run(aiops.refreshActiveAlerts);
}

function diagnoseAlert(alert: ActiveAlert): void {
  run(() => aiops.diagnoseAlert(alert).then(() => router.push("/aiops")));
}

function openDiagnostic(diagnosticId: string): void {
  run(() => aiops.selectDiagnostic(diagnosticId).then(() => router.push("/aiops")));
}

function openCaseDocument(documentId: string): void {
  run(() => router.push({ name: "knowledge", query: { documentId } }));
}
</script>

<template>
  <section class="aiops-overview" aria-label="AI 运维中心总览">
    <div class="aiops-overview__scroll">
      <header class="aiops-overview__hero">
        <div class="aiops-overview__hero-copy">
          <p>值班态势</p>
          <h2>告警、诊断、证据与案例，在同一个工作区闭环</h2>
          <span>这里的数字来自当前账号的真实告警订阅、诊断任务与案例归档，随实时事件更新。</span>
        </div>
        <RouterLink class="aiops-overview__cta" to="/aiops">
          <Stethoscope :size="16" aria-hidden="true" />
          发起诊断
        </RouterLink>
      </header>

      <AppLoadingState v-if="aiops.isLoading && aiops.history.length === 0" label="正在加载运维态势" />
      <AppErrorState
        v-else-if="aiops.errorMessage && aiops.history.length === 0"
        :can-retry="true"
        :message="aiops.errorMessage"
        @retry="run(aiops.initialize)"
      />

      <div v-else class="aiops-overview__body">
        <div class="aiops-overview__stats" aria-label="态势概览">
          <RouterLink class="aiops-overview__stat" to="/aiops/alerts">
            <span class="aiops-overview__stat-label"><BellRing :size="14" aria-hidden="true" />活跃告警</span>
            <strong class="aiops-overview__stat-value">{{ aiops.activeAlerts.length }}</strong>
            <span class="aiops-overview__stat-hint">{{ alertSummary }}</span>
          </RouterLink>
          <RouterLink class="aiops-overview__stat" to="/aiops">
            <span class="aiops-overview__stat-label"><Activity :size="14" aria-hidden="true" />当前诊断</span>
            <strong class="aiops-overview__stat-value aiops-overview__stat-value--text">{{ activeQuery }}</strong>
            <span class="aiops-overview__stat-hint"><AsyncStatusBadge :compact="true" :status="activeStatus" /></span>
          </RouterLink>
          <RouterLink class="aiops-overview__stat" to="/aiops/history">
            <span class="aiops-overview__stat-label"><History :size="14" aria-hidden="true" />诊断历史</span>
            <strong class="aiops-overview__stat-value">{{ aiops.history.length }}</strong>
            <span class="aiops-overview__stat-hint">最近记录与完整证据链</span>
          </RouterLink>
          <RouterLink class="aiops-overview__stat" to="/aiops/cases">
            <span class="aiops-overview__stat-label"><BookOpenCheck :size="14" aria-hidden="true" />沉淀案例</span>
            <strong class="aiops-overview__stat-value">{{ aiops.diagnosticCases.length }}</strong>
            <span class="aiops-overview__stat-hint">已归档并参与知识检索</span>
          </RouterLink>
        </div>

        <section class="aiops-overview__section" aria-label="最近告警">
          <div class="aiops-overview__section-heading">
            <div>
              <p>实时信号</p>
              <h3>最近活跃告警</h3>
            </div>
            <RouterLink to="/aiops/alerts">查看全部<Radar :size="14" aria-hidden="true" /></RouterLink>
          </div>
          <ActiveAlertList
            :alerts="recentAlerts"
            :error-message="aiops.alertsErrorMessage"
            :is-loading="aiops.alertsLoading"
            @diagnose="diagnoseAlert"
            @refresh="refreshAlerts"
          />
        </section>

        <div class="aiops-overview__columns">
          <section class="aiops-overview__section" aria-label="最近诊断">
            <div class="aiops-overview__section-heading">
              <div>
                <p>证据链</p>
                <h3>最近诊断</h3>
              </div>
              <RouterLink to="/aiops/history">查看全部</RouterLink>
            </div>
            <AiopsHistory
              :active-diagnostic-id="aiops.activeDiagnosticId"
              :tasks="recentHistory"
              @select="openDiagnostic"
            />
          </section>
          <section class="aiops-overview__section" aria-label="最近案例">
            <div class="aiops-overview__section-heading">
              <div>
                <p>知识沉淀</p>
                <h3>最近案例</h3>
              </div>
              <RouterLink to="/aiops/cases">查看全部</RouterLink>
            </div>
            <AiopsCaseLibrary
              :cases="recentCases"
              @open-document="openCaseDocument"
              @select="openDiagnostic"
            />
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.aiops-overview { background: var(--surface-raised); height: 100%; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.aiops-overview__scroll { display: grid; gap: 1.2rem; margin: 0 auto; max-width: 1180px; padding: clamp(1rem, 2.6vw, 1.9rem); }
.aiops-overview__hero { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); display: flex; gap: 1.2rem; justify-content: space-between; padding: clamp(1rem, 2.2vw, 1.5rem); }
.aiops-overview__hero p { color: var(--accent-strong); font-size: 0.7rem; font-weight: 600; letter-spacing: 0.03em; margin: 0 0 0.3rem; }
.aiops-overview__hero h2 { font-size: clamp(0.98rem, 1.25vw, 1.1rem); font-weight: 600; line-height: 1.4; margin: 0 0 0.35rem; }
.aiops-overview__hero span { color: var(--text-secondary); font-size: 0.8rem; }
.aiops-overview__cta { align-items: center; background: var(--accent-solid); border-radius: var(--radius-md); color: #ffffff; display: inline-flex; flex: none; font-size: 0.8rem; font-weight: 600; gap: 0.35rem; min-height: 2.15rem; padding: 0 0.9rem; text-decoration: none; transition: filter var(--transition-fast); }
.aiops-overview__cta:hover { filter: brightness(1.08); }
.aiops-overview__body { display: grid; gap: 1.2rem; }
.aiops-overview__stats { display: grid; gap: 0.8rem; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.aiops-overview__stat { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); display: grid; gap: 0.35rem; padding: 0.95rem 1rem; text-decoration: none; transition: border-color var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast); }
.aiops-overview__stat:hover { border-color: var(--accent-border); background: var(--surface-hover); }
.aiops-overview__stat-label { align-items: center; color: var(--text-tertiary); display: inline-flex; font-size: 0.74rem; font-weight: 600; gap: 0.35rem; }
.aiops-overview__stat-value { color: var(--text-primary); font-family: var(--font-mono); font-size: 1.3rem; font-variant-numeric: tabular-nums; font-weight: 600; line-height: 1.1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aiops-overview__stat-value--text { font-family: var(--font-sans); font-size: 0.95rem; line-height: 1.45; }
.aiops-overview__stat-hint { color: var(--text-tertiary); font-size: 0.74rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aiops-overview__section { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-md); overflow: hidden; }
.aiops-overview__section-heading { align-items: center; display: flex; justify-content: space-between; padding: 0.85rem 1rem; }
.aiops-overview__section-heading p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 600; margin: 0 0 0.18rem; }
.aiops-overview__section-heading h3 { font-size: 0.92rem; font-weight: 600; margin: 0; }
.aiops-overview__section-heading a { align-items: center; color: var(--accent-strong); display: inline-flex; font-size: 0.76rem; font-weight: 600; gap: 0.3rem; text-decoration: none; }
.aiops-overview__section-heading a:hover { text-decoration: underline; }
.aiops-overview__section :deep(.active-alert-list) { border-bottom: 0; border-top: 1px solid var(--line); }
.aiops-overview__section :deep(.active-alert-list > header) { display: none; }
.aiops-overview__section :deep(.aiops-history) { border-top: 1px solid var(--line); }
.aiops-overview__section :deep(.aiops-history > header) { display: none; }
.aiops-overview__section :deep(.aiops-case-library) { border-top: 1px solid var(--line); }
.aiops-overview__section :deep(.aiops-case-library > header) { display: none; }
.aiops-overview__columns { display: grid; gap: 1.2rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 1100px) { .aiops-overview__stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .aiops-overview__hero { align-items: flex-start; flex-direction: column; } .aiops-overview__stats { grid-template-columns: minmax(0, 1fr); } .aiops-overview__columns { grid-template-columns: minmax(0, 1fr); } }
</style>

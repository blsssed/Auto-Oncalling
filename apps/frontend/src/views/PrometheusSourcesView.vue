<script setup lang="ts">
import {
  Activity,
  CheckCircle2,
  Database,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  TriangleAlert
} from "lucide-vue-next";
import { computed, onMounted, reactive, watch } from "vue";

import type { PrometheusSourceMutationRequest } from "@agent-py/api-contracts";

import AppLoadingState from "../components/AppLoadingState.vue";
import MonitorSubNav from "../components/MonitorSubNav.vue";
import { usePrometheusStore } from "../stores/prometheus";

const prometheus = usePrometheusStore();
const draft = reactive<PrometheusSourceMutationRequest>({
  name: "",
  baseUrl: "",
  username: "",
  password: "",
  enabled: true,
  timeoutSeconds: 10,
  maxSeries: 20
});
const isNew = computed(() => prometheus.selected === null);

watch(() => prometheus.selected, (source) => {
  if (source === null) return;
  Object.assign(draft, {
    name: source.name,
    baseUrl: source.baseUrl,
    username: source.username ?? "",
    password: "",
    enabled: source.enabled,
    timeoutSeconds: source.timeoutSeconds,
    maxSeries: source.maxSeries
  });
}, { immediate: true });

onMounted(() => { void prometheus.initialize().catch(() => undefined); });

function newSource(): void {
  prometheus.select("");
  Object.assign(draft, {
    name: "",
    baseUrl: "http://127.0.0.1:9090",
    username: "",
    password: "",
    enabled: true,
    timeoutSeconds: 10,
    maxSeries: 20
  });
}

function run(operation: () => Promise<void>): void {
  void operation().catch(() => undefined);
}
</script>

<template>
  <section class="prom-view" aria-label="Prometheus 数据源管理">
    <MonitorSubNav />
    <header class="prom-view__header">
      <div><p>监控中心</p><h2>数据源管理</h2><span>接入自己的 Prometheus，供 Prometheus 指标监控查询真实指标。</span></div>
      <button type="button" title="新建数据源" @click="newSource"><Plus :size="16" aria-hidden="true" />新建数据源</button>
    </header>
    <AppLoadingState v-if="prometheus.isLoading" label="正在加载数据源" />
    <div v-else class="prom-view__workspace">
      <aside class="prom-view__list" aria-label="数据源列表">
        <button v-for="source in prometheus.sources" :key="source.id" type="button" :class="{ 'prom-view__source--active': prometheus.selectedId === source.id }" @click="prometheus.select(source.id)">
          <span class="prom-view__source-icon"><Database :size="16" aria-hidden="true" /></span>
          <span><strong>{{ source.name }}</strong><small>{{ source.baseUrl }} · {{ source.enabled ? '已启用' : '已停用' }}</small></span>
          <CheckCircle2 v-if="source.lastCheck?.ok" :size="15" class="prom-view__ok" aria-label="连接正常" />
          <TriangleAlert v-else-if="source.lastCheck" :size="15" class="prom-view__bad" aria-label="连接异常" />
        </button>
        <p v-if="prometheus.sources.length === 0">还没有数据源，点击右上角新建。</p>
      </aside>

      <main class="prom-view__editor">
        <form @submit.prevent="run(() => isNew ? prometheus.create(draft) : prometheus.update(draft))">
          <header><div><p>{{ isNew ? '新建数据源' : '数据源配置' }}</p><h3>{{ draft.name || '未命名 Prometheus' }}</h3></div><label class="prom-view__toggle"><input v-model="draft.enabled" type="checkbox" /><span>启用</span></label></header>
          <div class="prom-view__fields">
            <label><span>数据源名称</span><input v-model.trim="draft.name" required maxlength="120" /></label>
            <label class="prom-view__url"><span>Prometheus 地址</span><input v-model.trim="draft.baseUrl" type="url" required maxlength="2048" placeholder="http://127.0.0.1:9090" /></label>
            <label><span>用户名（可选）</span><input v-model.trim="draft.username" autocomplete="off" maxlength="240" /></label>
            <label><span>密码（可选，留空保留旧值）</span><input v-model="draft.password" type="password" autocomplete="new-password" maxlength="512" /></label>
            <label><span>超时（秒）</span><input v-model.number="draft.timeoutSeconds" type="number" min="1" max="300" required /></label>
            <label><span>序列上限</span><input v-model.number="draft.maxSeries" type="number" min="1" max="100" required /></label>
          </div>
          <div class="prom-view__commands">
            <button v-if="prometheus.selected" type="button" :disabled="prometheus.checkingId === prometheus.selected.id" @click="run(() => prometheus.check(prometheus.selected!.id))"><RefreshCw :size="15" :class="{ spin: prometheus.checkingId === prometheus.selected.id }" aria-hidden="true" />{{ prometheus.checkingId === prometheus.selected.id ? '检查中' : '检查连接' }}</button>
            <button v-if="prometheus.selected" type="button" class="prom-view__delete" :disabled="prometheus.isSaving" @click="run(() => prometheus.remove(prometheus.selected!.id))"><Trash2 :size="15" aria-hidden="true" />删除</button>
            <button type="submit" class="prom-view__save" :disabled="prometheus.isSaving"><Save :size="15" aria-hidden="true" />{{ prometheus.isSaving ? '保存中' : '保存数据源' }}</button>
          </div>
        </form>

        <section class="prom-view__inspection" aria-label="数据源检查结果">
          <header><div><p>连通性</p><h3>检查状态</h3></div><Activity :size="18" aria-hidden="true" /></header>
          <div v-if="prometheus.selected?.lastCheck" class="prom-view__check-summary" :class="{ 'prom-view__check-summary--failed': !prometheus.selected.lastCheck.ok }">
            <CheckCircle2 v-if="prometheus.selected.lastCheck.ok" :size="17" aria-hidden="true" /><TriangleAlert v-else :size="17" aria-hidden="true" />
            <span><strong>{{ prometheus.selected.lastCheck.ok ? '连接正常' : '连接异常' }}</strong><small>{{ prometheus.selected.lastCheck.ok ? `检查时间：${prometheus.selected.lastCheck.checkedAt ?? '-'}` : prometheus.selected.lastCheck.error }}</small></span>
          </div>
          <p v-else class="prom-view__empty">保存数据源后执行检查，这里会展示真实的探测结果。</p>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.prom-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; }
.prom-view__header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; padding: 0.85rem clamp(1rem, 3vw, 2rem); }
.prom-view__header p, .prom-view__editor header p, .prom-view__inspection header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 600; margin: 0 0 0.25rem; }
.prom-view__header h2 { font-size: 1.05rem; margin: 0; }
.prom-view__header span { color: var(--text-secondary); display: block; font-size: 0.78rem; margin-top: 0.3rem; }
.prom-view__header > button, .prom-view__commands button { align-items: center; border: 1px solid var(--line-strong); border-radius: 0.4rem; display: inline-flex; font-size: 0.76rem; font-weight: 600; gap: 0.35rem; min-height: 2.2rem; padding: 0 0.7rem; }
.prom-view__workspace { display: grid; grid-template-columns: minmax(15rem, 20rem) minmax(0, 1fr); min-height: 0; }
.prom-view__list { border-right: 1px solid var(--line); display: grid; gap: 0.35rem; overflow-y: auto; padding: 0.75rem; }
.prom-view__list > button { align-items: center; border-radius: 0.35rem; display: grid; gap: 0.6rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: 0.7rem; text-align: left; }
.prom-view__list > button:hover, .prom-view__source--active { background: var(--surface-hover); }
.prom-view__source-icon { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 0.35rem; display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.prom-view__list strong, .prom-view__list small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prom-view__list strong { font-size: 0.8rem; }.prom-view__list small { color: var(--text-tertiary); font-size: 0.68rem; margin-top: 0.2rem; }.prom-view__ok { color: var(--status-success-text); }.prom-view__bad { color: var(--status-danger-text); }
.prom-view__editor { display: grid; grid-template-columns: minmax(24rem, 1fr) minmax(18rem, 0.72fr); min-height: 0; overflow: hidden; }
.prom-view__editor > form, .prom-view__inspection { min-width: 0; overflow-y: auto; padding: clamp(1rem, 3vw, 2rem); }
.prom-view__editor > form { border-right: 1px solid var(--line); }
.prom-view__editor header { align-items: center; display: flex; justify-content: space-between; }.prom-view__editor h3 { font-size: 1rem; margin: 0; }
.prom-view__toggle { align-items: center; display: flex; font-size: 0.76rem; gap: 0.4rem; }.prom-view__toggle input { accent-color: var(--accent-strong); height: 1rem; width: 1rem; }
.prom-view__fields { display: grid; gap: 0.9rem; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 1.4rem; }.prom-view__fields label { color: var(--text-secondary); display: grid; font-size: 0.74rem; font-weight: 600; gap: 0.4rem; }.prom-view__url { grid-column: 1 / -1; }
.prom-view__fields input { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 0.4rem; color: var(--text-primary); font: inherit; min-height: 2.1rem; padding: 0 0.65rem; width: 100%; }
.prom-view__commands { display: flex; flex-wrap: wrap; gap: 0.55rem; justify-content: flex-end; margin-top: 1.4rem; }.prom-view__save { background: var(--accent-solid); border-color: var(--accent-solid) !important; color: white; }.prom-view__delete { color: var(--status-danger-text); margin-right: auto; }
.prom-view__inspection { background: var(--surface); }.prom-view__check-summary { align-items: center; background: var(--status-success-bg); border: 1px solid var(--status-success-border); display: flex; gap: 0.65rem; margin-top: 1.2rem; padding: 0.75rem; }.prom-view__check-summary--failed { background: var(--status-danger-bg); border-color: var(--status-danger-border); }.prom-view__check-summary strong, .prom-view__check-summary small { display: block; }.prom-view__check-summary small { font-size: 0.7rem; margin-top: 0.15rem; }
.prom-view__empty { color: var(--text-tertiary); font-size: 0.72rem; line-height: 1.5; margin-top: 1rem; }
.spin { animation: spin 0.8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .prom-view__editor { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }.prom-view__editor > form { border-bottom: 1px solid var(--line); border-right: 0; overflow: visible; }.prom-view__inspection { overflow: visible; } }
@media (max-width: 760px) { .prom-view { height: auto; }.prom-view__header { align-items: flex-start; gap: 1rem; }.prom-view__workspace { grid-template-columns: minmax(0, 1fr); }.prom-view__list { border-bottom: 1px solid var(--line); border-right: 0; max-height: 15rem; }.prom-view__editor { display: block; }.prom-view__fields { grid-template-columns: minmax(0, 1fr); }.prom-view__url { grid-column: auto; } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>

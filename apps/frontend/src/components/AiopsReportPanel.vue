<script setup lang="ts">
import { FileCheck2, FileClock, FileWarning } from "lucide-vue-next";

import { ref, watch } from "vue";
import type { AiopsStructuredDiagnosis, ConfirmAiopsDiagnosticCaseRequest } from "@agent-py/api-contracts";
import StructuredDiagnosis from "./StructuredDiagnosis.vue";
import MarkdownContent from "./MarkdownContent.vue";
import UserFeedbackControl from "./UserFeedbackControl.vue";

export interface AiopsReportDisplay {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly createdAt: string | null;
  readonly diagnosis?: AiopsStructuredDiagnosis;
}

const props = defineProps<{
  readonly report: AiopsReportDisplay | null;
  readonly isRunning: boolean;
  readonly hasTask: boolean;
  readonly taskFailed: boolean;
  readonly readOnly?: boolean;
  readonly confirmed?: boolean;
  readonly confirming?: boolean;
}>();
const emit = defineEmits<{ citation: [id: string]; confirm: [body: ConfirmAiopsDiagnosticCaseRequest] }>();
const rootCause = ref("");
const remediation = ref("");
const acknowledged = ref(false);
watch(() => props.report?.id, () => { rootCause.value = ""; remediation.value = ""; acknowledged.value = false; });
function confirm(): void {
  if (!acknowledged.value || !rootCause.value.trim() || !remediation.value.trim()) return;
  emit("confirm", { confirmed: true, rootCause: rootCause.value.trim(), remediation: remediation.value.trim() });
}
</script>

<template>
  <section class="aiops-report" aria-label="最终诊断报告" aria-live="polite">
    <header class="aiops-report__header">
      <div>
        <p>诊断产物</p>
        <h3>最终诊断报告</h3>
      </div>
      <span v-if="report" class="aiops-report__state aiops-report__state--ready">
        <FileCheck2 :size="15" aria-hidden="true" />已生成
      </span>
      <span v-else-if="isRunning" class="aiops-report__state aiops-report__state--running">
        <FileClock :size="15" aria-hidden="true" />生成中
      </span>
    </header>

    <article v-if="report" class="aiops-report__document">
      <div class="aiops-report__meta">
        <strong>{{ report.title }}</strong>
        <time v-if="report.createdAt" :datetime="report.createdAt">
          {{ new Date(report.createdAt).toLocaleString("zh-CN") }}
        </time>
      </div>
      <StructuredDiagnosis v-if="report.diagnosis" :diagnosis="report.diagnosis" @citation="emit('citation', $event)" />
      <MarkdownContent v-else :content="report.content" mode="report" />
      <details v-if="report.diagnosis"><summary>查看 Markdown 报告</summary><MarkdownContent :content="report.content" mode="report" /></details>
      <footer v-if="!readOnly">
        <p v-if="confirmed" role="status">已人工确认入库</p>
        <form v-else @submit.prevent="confirm" class="case-confirmation">
          <h4>人工确认后入库</h4>
          <p>复核根因和处理建议。确认后案例才参与后续检索。</p>
          <label>确认的根因<textarea v-model="rootCause" aria-label="确认的根因" required maxlength="4000" /></label>
          <label>确认的处理建议<textarea v-model="remediation" aria-label="确认的处理建议" required maxlength="4000" /></label>
          <label class="acknowledge"><input v-model="acknowledged" type="checkbox" />我已复核以上内容</label>
          <button :disabled="isRunning || confirming || !acknowledged || !rootCause.trim() || !remediation.trim()">{{ confirming ? '正在保存' : '确认并保存案例' }}</button>
        </form>
        <UserFeedbackControl target-type="diagnostic_report" :target-id="report.id" />
      </footer>
    </article>

    <div v-else-if="isRunning" class="aiops-report__empty aiops-report__empty--running">
      <FileClock :size="22" aria-hidden="true" />
      <div>
        <strong>正在等待诊断证据汇总</strong>
        <p>完成规划、工具查询与重规划后，将自动生成并保存中文诊断报告。</p>
      </div>
    </div>

    <div v-else-if="taskFailed" class="aiops-report__empty aiops-report__empty--failed">
      <FileWarning :size="22" aria-hidden="true" />
      <div>
        <strong>本次诊断未沉淀报告</strong>
        <p>诊断在报告持久化前失败，请查看下方过程和右侧工具证据后重新执行。</p>
      </div>
    </div>

    <div v-else class="aiops-report__empty">
      <FileClock :size="22" aria-hidden="true" />
      <div>
        <strong>{{ hasTask ? "报告尚未生成" : "等待诊断任务" }}</strong>
        <p>{{ hasTask ? "任务完成后，最终报告会显示在这里。" : "选择历史诊断或发起新任务后，在这里阅读最终报告。" }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.case-confirmation { display: grid; gap: .6rem; margin-bottom: 1rem; }
.case-confirmation h4, .case-confirmation p { margin: 0; font-size: .8rem; }
.case-confirmation label { display: grid; gap: .3rem; font-size: .8rem; }
.case-confirmation textarea { border: 1px solid var(--line); padding: .5rem; min-width: 0; width: 100%; }
.case-confirmation .acknowledge { display: flex; align-items: center; gap: .5rem; }
.case-confirmation button { background: var(--accent-solid); color: #ffffff; padding: .6rem; border-radius: .4rem; }
.case-confirmation button:disabled { opacity: .5; cursor: not-allowed; }
details > summary { cursor: pointer; padding: .75rem; font-size: .8rem; }

.aiops-report { border-bottom: 1px solid var(--line); display: grid; grid-template-rows: auto auto; min-height: 0; min-width: 0; overflow: hidden; padding: 1.25rem; }
.aiops-report__header { align-items: center; display: flex; justify-content: space-between; }
.aiops-report__header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 600; margin: 0 0 0.3rem; }
.aiops-report__header h3 { font-size: 1rem; font-weight: 600; margin: 0; }
.aiops-report__state { align-items: center; border: 1px solid; display: inline-flex; font-size: 0.72rem; font-weight: 600; gap: 0.35rem; min-height: 2rem; padding: 0.25rem 0.55rem; }
.aiops-report__state--ready { background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text); }
.aiops-report__state--running { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-report__document { background: var(--surface-raised); border: 1px solid var(--line); display: grid; grid-template-rows: auto; margin-top: 1rem; min-height: 0; min-width: 0; overflow: hidden; }
.aiops-report__meta { align-items: baseline; border-bottom: 1px solid var(--line); display: flex; gap: 0.75rem; justify-content: space-between; padding: 0.8rem 1rem; }
.aiops-report__meta strong { font-size: 0.84rem; font-weight: 600; }
.aiops-report__meta time { color: var(--text-tertiary); font-size: 0.72rem; white-space: nowrap; }
.aiops-report__document > :deep(.markdown-content) { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: clamp(1rem, 3vw, 2rem); }
.aiops-report__document footer { border-top: 1px solid var(--line); padding: 0.65rem 1rem; }
.aiops-report__empty { align-items: center; background: var(--surface); border: 1px dashed var(--line-strong); color: var(--text-tertiary); display: flex; gap: 0.85rem; margin-top: 1rem; min-height: 6.5rem; padding: 1rem; }
.aiops-report__empty svg { flex: 0 0 auto; }
.aiops-report__empty strong { color: var(--text-secondary); display: block; font-size: 0.84rem; }
.aiops-report__empty p { font-size: 0.78rem; line-height: 1.55; margin: 0.3rem 0 0; }
.aiops-report__empty--running { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-report__empty--failed { background: var(--status-danger-bg); border-color: var(--status-danger-border); color: var(--status-danger-text); }
@media (max-width: 560px) { .aiops-report { padding: 1rem; } .aiops-report__meta { align-items: flex-start; flex-direction: column; } .aiops-report__meta time { white-space: normal; } }
</style>

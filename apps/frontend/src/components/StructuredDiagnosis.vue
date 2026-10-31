<script setup lang="ts">
import type { AiopsStructuredDiagnosis } from "@agent-py/api-contracts";
defineProps<{ diagnosis: AiopsStructuredDiagnosis }>();
defineEmits<{ citation: [evidenceId: string] }>();
const labels = { supported: "有证据支持", insufficient_evidence: "证据不足", conflicting_evidence: "证据冲突" };
</script>

<template>
  <div class="diagnosis">
    <span class="assessment" :data-assessment="diagnosis.assessment">{{ labels[diagnosis.assessment] }}</span>
    <h3>{{ diagnosis.summary }}</h3>
    <p class="traceability">引用校验表示结论可追溯；根因仍需结合场景验证。</p>
    <article v-for="hypothesis in diagnosis.hypotheses" :key="hypothesis.id" class="hypothesis">
      <h4>候选根因 · {{ hypothesis.title }}</h4>
      <div class="evidence-columns">
        <section><h5>支持证据</h5><p v-if="!hypothesis.supportingEvidence.length">未获取</p>
          <button v-for="(item, i) in hypothesis.supportingEvidence" :key="`${item.evidenceId}-${i}`" @click="$emit('citation', item.evidenceId)">
            <q>{{ item.excerpt }}</q><small>查看证据 ↗</small>
          </button>
        </section>
        <section><h5>反对证据</h5><p v-if="!hypothesis.opposingEvidence.length">未获取</p>
          <button v-for="(item, i) in hypothesis.opposingEvidence" :key="`${item.evidenceId}-${i}`" @click="$emit('citation', item.evidenceId)">
            <q>{{ item.excerpt }}</q><small>查看证据 ↗</small>
          </button>
        </section>
      </div>
    </article>
    <section v-for="group in [
      {title: '缺失信息', items: diagnosis.missingInformation},
      {title: '处理建议 · 由操作者执行', items: diagnosis.recommendations},
      {title: '验证步骤', items: diagnosis.verificationSteps}
    ]" :key="group.title"><h4>{{ group.title }}</h4><ul v-if="group.items.length"><li v-for="(item, i) in group.items" :key="i">{{ item }}</li></ul><p v-else>未提供</p></section>
  </div>
</template>

<style scoped>
.diagnosis { padding: 1.25rem; overflow-wrap: anywhere; }
.assessment { background: var(--status-running-bg); color: var(--status-running-text); border: 1px solid var(--line); border-radius: 1rem; padding: .3rem .7rem; font-size: .75rem; }
.assessment[data-assessment="supported"] { background: var(--status-success-bg); color: var(--status-success-text); }
.assessment[data-assessment="conflicting_evidence"] { background: var(--status-danger-bg); color: var(--status-danger-text); }
h3 { font-size: 1.15rem; line-height: 1.6; margin: 1rem 0 .5rem; } h4 { font-size: .9rem; margin: 1.25rem 0 .6rem; } h5 { font-size: .8rem; margin: 0 0 .5rem; }
.traceability, p { font-size: .75rem; color: var(--text-tertiary); line-height: 1.6; }
.hypothesis { border-top: 1px solid var(--line); }
.evidence-columns { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; }
button { display: grid; text-align: left; gap: .5rem; padding: .75rem; background: var(--surface); border: 1px solid var(--line); width: 100%; margin-bottom: .5rem; border-radius: .4rem; color: var(--text-primary); }
button:hover { border-color: var(--accent); } small { color: var(--accent); } q, li { font-size: .8rem; line-height: 1.7; } ul { padding-left: 1.2rem; }
@media(max-width: 560px) { .evidence-columns { grid-template-columns: 1fr; } .diagnosis { padding: 1rem; } }
</style>

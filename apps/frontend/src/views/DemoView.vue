<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import AiopsReportPanel from "../components/AiopsReportPanel.vue";
import AiopsEvidenceChain from "../components/AiopsEvidenceChain.vue";
import { parseRecording, replayChain, type ReplayRecording } from "../aiops/replay";

const recordings = ref<ReplayRecording[]>([]);
const selected = ref(0);
const step = ref(0);
const speed = ref(1);
const playing = ref(false);
const error = ref("");
let timer: ReturnType<typeof setInterval> | undefined;
const recording = computed(() => recordings.value[selected.value]);
const chain = computed(() => recording.value ? replayChain(recording.value, step.value) : null);
const report = computed(() => chain.value?.reports.at(-1) ?? null);
function pause(): void { playing.value = false; clearInterval(timer); timer = undefined; }
function reset(): void { pause(); step.value = 0; }
function play(): void {
  if (!recording.value) return;
  if (step.value >= recording.value.chain.steps.length) step.value = 0;
  pause(); playing.value = true;
  timer = setInterval(() => {
    step.value += 1;
    if (step.value >= (recording.value?.chain.steps.length ?? 0)) pause();
  }, 2000 / speed.value);
}
async function locate(id: string): Promise<void> {
  await nextTick();
  const target = document.getElementById(`evidence-${id}`);
  if (target instanceof HTMLDetailsElement) target.open = true;
  target?.scrollIntoView({ block: "center" });
}
onMounted(async () => {
  try {
    const response = await fetch("/demo/manifest.json");
    const manifest: unknown = await response.json();
    if (!Array.isArray(manifest)) throw new Error("录制清单无效");
    for (const file of manifest) {
      if (typeof file !== "string" || !/^[a-z0-9-]+\.json$/.test(file)) throw new Error("录制文件名无效");
      const response = await fetch(`/demo/${file}`);
      recordings.value.push(parseRecording(await response.json()));
    }
  } catch { error.value = "录制加载失败，请检查静态演示文件。"; }
});
onBeforeUnmount(pause);
</script>

<template>
  <main class="demo-page">
    <header><RouterLink to="/demo" class="brand">Auto Oncall</RouterLink><RouterLink to="/login">进入诊断工作台 ↗</RouterLink></header>
    <section class="intro"><p>公开演示 · 离线回放</p><h1>让每一次根因判断<br />都有证据可查。</h1><p>查看日志如何改变调查计划，以及证据不足时如何停止并提出下一步。</p></section>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="!recordings.length && !error" class="awaiting">
      <span>录制待采集</span><h2>等待 CLS 测试环境的真实调查录制</h2>
      <p>计划覆盖定位成功、证据变化触发重新规划、证据不足三个场景。完成采集与脱敏后可在这里播放。</p>
    </section>
    <template v-if="recording">
      <nav class="controls" aria-label="回放控制">
        <label>场景<select v-model="selected" @change="reset"><option v-for="(item, i) in recordings" :key="i" :value="i">{{ item.title }}</option></select></label>
        <button @click="playing ? pause() : play()">{{ playing ? '暂停' : '播放' }}</button><button @click="reset">重置</button>
        <label>倍速<select v-model="speed" @change="playing && play()"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select></label>
        <label>步骤<select v-model="step" @change="pause"><option :value="0">开始</option><option v-for="(item, i) in recording.chain.steps" :key="item.id" :value="i + 1">{{ i + 1 }} · {{ item.phase }}</option></select></label>
      </nav>
      <p class="provenance">来源：真实 CLS 工具调用 · {{ recording.injectedFault ? '注入的测试故障，仅供演示' : '测试环境调查' }} · 已脱敏</p>
      <div class="replay-grid"><AiopsReportPanel :report="report" :has-task="true" :is-running="playing" :task-failed="false" :read-only="true" @citation="locate" /><AiopsEvidenceChain :chain="chain" :read-only="true" /></div>
    </template>
    <footer>结论可追溯 · 调查可重新规划 · 人工确认后形成案例</footer>
  </main>
</template>

<style scoped>
.demo-page { max-width: 1440px; padding: 0 clamp(1rem, 5vw, 4rem); margin: auto; min-height: 100vh; background: var(--surface-raised); }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; border-bottom: 1px solid var(--line); padding: 1.5rem 0; } a { color: var(--text-secondary); text-decoration: none; font-size: .8rem; } .brand { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); }
.intro { padding: 4rem 0 2.5rem; } .intro > p:first-child { color: var(--accent); font-weight: 600; font-size: .8rem; } h1 { font-size: clamp(2rem, 5vw, 4rem); line-height: 1.25; letter-spacing: -.04em; margin: 1rem 0; } p { line-height: 1.8; color: var(--text-secondary); font-size: .9rem; }
.awaiting { padding: clamp(1.5rem, 4vw, 3rem); border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: .7rem; margin-bottom: 3rem; background: var(--surface); } .awaiting span { font-size: .75rem; color: var(--accent); } h2 { font-size: 1.15rem; line-height: 1.6; }
.controls { display: flex; gap: 1rem; align-items: end; flex-wrap: wrap; padding: 1rem; border: 1px solid var(--line); } label { display: grid; gap: .4rem; font-size: .75rem; min-width: 0; } select, button { background: var(--surface); border: 1px solid var(--line); padding: .6rem; border-radius: .4rem; color: var(--text-primary); max-width: 100%; } button { cursor: pointer; } .replay-grid { display: grid; grid-template-columns: 1.3fr 1fr; border: 1px solid var(--line); } .provenance { font-size: .75rem; } footer { padding: 1.5rem 0; border-top: 1px solid var(--line); font-size: .75rem; color: var(--text-tertiary); }
@media(max-width: 860px) { .replay-grid { grid-template-columns: 1fr; } .intro { padding: 2.5rem 0 1.5rem; } }
</style>

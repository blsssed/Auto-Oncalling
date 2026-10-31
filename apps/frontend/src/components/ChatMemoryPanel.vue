<script setup lang="ts">
import { BrainCircuit } from "lucide-vue-next";
import { ref, watch } from "vue";

import type { ChatMemoryMode, ChatMemoryState } from "@agent-py/api-contracts";

const emit = defineEmits<{
  applyMemory: [mode: ChatMemoryMode];
  compactMemory: [];
}>();
const props = defineProps<{
  readonly memory: ChatMemoryState | null;
  readonly isUpdatingMemory: boolean;
}>();

const selectedMode = ref<ChatMemoryMode>(props.memory?.mode ?? "every_30_turns");

watch(
  () => props.memory?.mode,
  (mode) => {
    if (mode !== undefined) selectedMode.value = mode;
  }
);
</script>

<template>
  <aside class="chat-memory" aria-label="会话记忆设置">
    <div class="chat-memory__head">
      <span><BrainCircuit :size="15" aria-hidden="true" />上下文</span>
      <strong>{{ memory?.contextUsagePercent ?? 0 }}%</strong>
    </div>
    <progress :value="memory?.contextUsagePercent ?? 0" max="100" aria-label="上下文窗口占用" />
    <div class="chat-memory__actions">
      <select v-model="selectedMode" aria-label="记忆模式" :disabled="!memory || isUpdatingMemory">
        <option value="every_30_turns">每 30 轮压缩</option>
        <option value="context_70_percent">占用 70% 自动压缩</option>
        <option value="manual">手动压缩</option>
      </select>
      <button
        v-if="memory?.mode === 'manual' && selectedMode === 'manual'"
        class="chat-memory__apply"
        type="button"
        :disabled="isUpdatingMemory"
        @click="emit('compactMemory')"
      >{{ isUpdatingMemory ? "压缩中" : "立即压缩" }}</button>
      <button
        v-else
        class="chat-memory__apply"
        type="button"
        :disabled="!memory || isUpdatingMemory || selectedMode === memory?.mode"
        @click="emit('applyMemory', selectedMode)"
      >{{ isUpdatingMemory ? "应用中" : "应用" }}</button>
    </div>
  </aside>
</template>

<style scoped>
.chat-memory { border-bottom: 1px solid var(--line); display: grid; gap: 0.45rem; padding: 0.85rem 1rem; }
.chat-memory__head { align-items: center; display: flex; justify-content: space-between; }
.chat-memory__head span { align-items: center; color: var(--text-secondary); display: inline-flex; font-size: 0.74rem; font-weight: 600; gap: 0.35rem; }
.chat-memory__head strong { font-family: var(--font-mono); font-size: 0.8rem; font-variant-numeric: tabular-nums; font-weight: 600; }
progress { accent-color: var(--accent-solid); height: 0.35rem; width: 100%; }
.chat-memory__actions { display: grid; gap: 0.4rem; grid-template-columns: minmax(0, 1fr) auto; }
select { background: var(--surface); border: 1px solid var(--line); border-radius: 0.35rem; color: var(--text-primary); font-size: 0.7rem; min-width: 0; padding: 0.35rem; }
.chat-memory__apply { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 0.35rem; color: var(--text-primary); font-size: 0.7rem; padding: 0.35rem 0.55rem; white-space: nowrap; }
.chat-memory__apply:hover:not(:disabled) { border-color: var(--accent-border); color: var(--accent-strong); }
.chat-memory__apply:disabled { color: var(--text-tertiary); }
</style>

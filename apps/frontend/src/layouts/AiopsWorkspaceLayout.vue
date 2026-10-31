<script setup lang="ts">
import { onBeforeUnmount } from "vue";

import AiopsSubNav from "../components/AiopsSubNav.vue";
import { useAiopsStore } from "../stores/aiops";

const aiops = useAiopsStore();

// 只有离开整个 AI 运维中心时才清空状态；工作区内切换页签保留进行中的诊断。
onBeforeUnmount(() => {
  aiops.reset();
});
</script>

<template>
  <div class="aiops-workspace">
    <AiopsSubNav />
    <div class="aiops-workspace__body"><RouterView /></div>
  </div>
</template>

<style scoped>
.aiops-workspace { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-workspace__body { min-height: 0; overflow: hidden; }
@media (max-width: 860px) { .aiops-workspace__body { overflow: auto; } }
</style>

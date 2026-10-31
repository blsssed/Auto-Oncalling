<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import AiopsHistory from "../components/AiopsHistory.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import { useAiopsStore } from "../stores/aiops";

const aiops = useAiopsStore();
const router = useRouter();

onMounted(() => {
  void aiops.initialize().catch(() => undefined);
});

function retry(): void {
  void aiops.initialize().catch(() => undefined);
}

function selectDiagnostic(diagnosticId: string): void {
  void aiops
    .selectDiagnostic(diagnosticId)
    .then(() => router.push("/aiops"))
    .catch(() => undefined);
}
</script>

<template>
  <section class="aiops-sub-view" aria-label="诊断历史">
    <AppLoadingState v-if="aiops.isLoading && aiops.history.length === 0" label="正在加载诊断历史" />
    <AppErrorState v-else-if="aiops.errorMessage && aiops.history.length === 0" :can-retry="true" :message="aiops.errorMessage" @retry="retry" />
    <div v-else class="aiops-sub-view__body">
      <AiopsHistory :active-diagnostic-id="aiops.activeDiagnosticId" :tasks="aiops.history" @select="selectDiagnostic" />
    </div>
  </section>
</template>

<style scoped>
.aiops-sub-view { background: var(--surface-raised); display: grid; grid-template-rows: minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-sub-view__body { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
</style>

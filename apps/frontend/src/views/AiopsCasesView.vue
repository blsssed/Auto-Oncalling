<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import AiopsCaseLibrary from "../components/AiopsCaseLibrary.vue";
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

function selectCase(diagnosticId: string): void {
  void aiops
    .selectDiagnostic(diagnosticId)
    .then(() => router.push("/aiops"))
    .catch(() => undefined);
}

function openCaseDocument(documentId: string): void {
  void router.push({ name: "knowledge", query: { documentId } });
}
</script>

<template>
  <section class="aiops-sub-view" aria-label="诊断案例库">
    <AppLoadingState v-if="aiops.isLoading && aiops.diagnosticCases.length === 0" label="正在加载诊断案例" />
    <AppErrorState v-else-if="aiops.errorMessage && aiops.diagnosticCases.length === 0" :can-retry="true" :message="aiops.errorMessage" @retry="retry" />
    <div v-else class="aiops-sub-view__body">
      <AiopsCaseLibrary :cases="aiops.diagnosticCases" @open-document="openCaseDocument" @select="selectCase" />
    </div>
  </section>
</template>

<style scoped>
.aiops-sub-view { background: var(--surface-raised); display: grid; grid-template-rows: minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-sub-view__body { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
</style>

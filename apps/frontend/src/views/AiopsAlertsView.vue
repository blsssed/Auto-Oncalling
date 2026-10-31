<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import { useAiopsStore } from "../stores/aiops";

const aiops = useAiopsStore();
const router = useRouter();

onMounted(() => {
  void aiops.initialize().catch(() => undefined);
  aiops.subscribeActiveAlerts();
});

function diagnoseAlert(alert: Parameters<typeof aiops.diagnoseAlert>[0]): void {
  void aiops
    .diagnoseAlert(alert)
    .then(() => router.push("/aiops"))
    .catch(() => undefined);
}

function refresh(): void {
  void aiops.refreshActiveAlerts().catch(() => undefined);
}
</script>

<template>
  <section class="aiops-sub-view" aria-label="告警中心">
    <AppLoadingState v-if="aiops.isLoading && aiops.activeAlerts.length === 0" label="正在加载活跃告警" />
    <AppErrorState v-else-if="aiops.errorMessage && aiops.activeAlerts.length === 0" :can-retry="true" :message="aiops.errorMessage" @retry="refresh" />
    <div v-else class="aiops-sub-view__body">
      <ActiveAlertList
        :alerts="aiops.activeAlerts"
        :error-message="aiops.alertsErrorMessage"
        :is-loading="aiops.alertsLoading"
        @diagnose="diagnoseAlert"
        @refresh="refresh"
      />
    </div>
  </section>
</template>

<style scoped>
.aiops-sub-view { background: var(--surface-raised); display: grid; grid-template-rows: minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-sub-view__body { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
</style>

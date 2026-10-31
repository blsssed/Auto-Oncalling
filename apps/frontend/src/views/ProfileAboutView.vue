<script setup lang="ts">
import { CircleDot, TriangleAlert } from "lucide-vue-next";
import { onMounted, ref } from "vue";

import { getFrontendFoundationHealth } from "../foundation";
import { createRuntimeHealthClient } from "../runtimeHealth";

const frontend = getFrontendFoundationHealth();
const backend = ref<{ version: string } | null>(null);
const isConnected = ref<boolean | null>(null);

onMounted(() => {
  void createRuntimeHealthClient()
    .health()
    .then((health) => {
      backend.value = { version: health.version };
      isConnected.value = true;
    })
    .catch(() => {
      isConnected.value = false;
    });
});
</script>

<template>
  <section class="profile-about" aria-label="关于">
    <div class="profile-about__card">
      <h3>关于</h3>
      <div class="profile-about__row"><span>前端版本</span><strong>{{ frontend.version }}</strong></div>
      <div class="profile-about__row">
        <span>后端服务</span>
        <strong>super-ai-backend</strong>
      </div>
      <div class="profile-about__row">
        <span>后端连接</span>
        <strong :class="isConnected === false ? 'profile-about__bad' : 'profile-about__ok'">
          <CircleDot v-if="isConnected !== false" :size="15" aria-hidden="true" />
          <TriangleAlert v-else :size="15" aria-hidden="true" />
          {{ isConnected === null ? "检测中" : isConnected ? "已连接" : "连接异常" }}
        </strong>
      </div>
      <div v-if="backend !== null" class="profile-about__row">
        <span>后端版本</span><strong>{{ backend.version }}</strong>
      </div>
    </div>
    <p class="profile-about__note">
      Agent Py 是一个本地优先的 AIOps 工作台：对话、知识库、智能诊断与 MCP 工具都在你自己的机器上运行。
    </p>
  </section>
</template>

<style scoped>
.profile-about { display: grid; gap: 0.9rem; max-width: 34rem; }
.profile-about__card { background: var(--canvas); border: 1px solid var(--line); border-radius: var(--radius-md); display: grid; gap: 0.6rem; padding: 1rem 1.1rem; }
.profile-about__card h3 { font-size: 0.9rem; font-weight: 600; margin: 0; }
.profile-about__row { align-items: center; display: flex; justify-content: space-between; gap: 0.8rem; }
.profile-about__row span { color: var(--text-tertiary); font-size: 0.78rem; }
.profile-about__row strong { align-items: center; display: inline-flex; font-size: 0.82rem; gap: 0.3rem; }
.profile-about__ok { color: var(--status-success-text); }
.profile-about__bad { color: var(--status-danger-text); }
.profile-about__note { color: var(--text-tertiary); font-size: 0.78rem; margin: 0; }
</style>

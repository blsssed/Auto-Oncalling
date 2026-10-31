<script setup lang="ts">
import { CircleDot, LogOut, Moon, Sparkles, Sun, TriangleAlert } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import WorkspaceNavigation from "../components/WorkspaceNavigation.vue";
import ChatSessionList from "../components/ChatSessionList.vue";
import { createRuntimeHealthClient } from "../runtimeHealth";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { useThemeStore } from "../stores/theme";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const chat = useChatStore();
const theme = useThemeStore();
theme.initialize();
const routeTitle = computed(() => (typeof route.meta.title === "string" ? route.meta.title : "工作台"));
const routeEyebrow = computed(() => (route.path.startsWith("/aiops") ? "AI 运维中心" : "AI 工作台"));
const initials = computed(() => auth.user?.displayName.slice(0, 1).toUpperCase() ?? "用");
const isConnected = ref(true);

onMounted(() => {
  void createRuntimeHealthClient().health().then(() => {
    isConnected.value = true;
  }).catch(() => {
    isConnected.value = false;
  });
});

async function logout(): Promise<void> {
  try {
    await auth.logout();
  } finally {
    await router.replace("/login");
  }
}

function runChat(operation: () => Promise<unknown>): void {
  void operation().catch(() => undefined);
}
</script>

<template>
  <div class="workspace-layout">
    <aside class="workspace-layout__rail">
      <RouterLink class="workspace-layout__brand" to="/chat" aria-label="Auto Oncall 工作台">
        <Sparkles :size="19" stroke-width="1.8" aria-hidden="true" />
        <span>Auto Oncall</span>
        <small>智能工作台</small>
      </RouterLink>
      <WorkspaceNavigation :active-path="route.path">
        <template #chat-history>
          <ChatSessionList
            :active-session-id="chat.activeSessionId"
            :sessions="chat.sessions"
            variant="rail"
            @create="runChat(chat.newSession)"
            @delete="runChat(() => chat.deleteSession($event))"
            @select="runChat(() => chat.selectSession($event))"
          />
        </template>
      </WorkspaceNavigation>
      <div class="workspace-layout__account">
        <RouterLink
          class="workspace-layout__profile"
          to="/profile"
          title="个人中心"
          aria-label="打开个人中心"
        >
          <span class="workspace-layout__avatar" aria-hidden="true">{{ initials }}</span>
          <span class="workspace-layout__identity">
            <strong>{{ auth.user?.displayName }}</strong>
            <small>{{ auth.user?.email }}</small>
          </span>
        </RouterLink>
        <button type="button" title="退出登录" aria-label="退出登录" @click="logout">
          <LogOut :size="17" aria-hidden="true" />
        </button>
      </div>
    </aside>
    <section class="workspace-layout__main">
      <header class="workspace-layout__header">
        <div>
          <p>{{ routeEyebrow }}</p>
          <h1>{{ routeTitle }}</h1>
        </div>
        <div class="workspace-layout__header-actions">
          <button
            type="button"
            class="workspace-layout__theme"
            title="切换主题"
            aria-label="切换主题"
            @click="theme.toggle()"
          >
            <Moon v-if="theme.resolved === 'light'" :size="16" aria-hidden="true" />
            <Sun v-else :size="16" aria-hidden="true" />
          </button>
          <span class="workspace-layout__status" :class="{ 'workspace-layout__status--degraded': !isConnected }" role="status" aria-live="polite">
            <CircleDot v-if="isConnected" :size="15" aria-hidden="true" />
            <TriangleAlert v-else :size="15" aria-hidden="true" />
            {{ isConnected ? "服务已连接" : "服务连接异常" }}
          </span>
        </div>
      </header>
      <main class="workspace-layout__content"><RouterView /></main>
    </section>
    <div class="workspace-layout__mobile-nav"><WorkspaceNavigation :active-path="route.path" compact /></div>
  </div>
</template>

<style scoped>
.workspace-layout { background: var(--canvas); color: var(--text-primary); display: grid; grid-template-columns: 16.5rem minmax(0, 1fr); min-height: 100vh; }
.workspace-layout__rail { background: var(--rail); display: flex; flex-direction: column; min-height: 100vh; padding: 1rem 0.7rem; }
.workspace-layout__brand { align-items: center; color: var(--rail-text); display: grid; gap: 0 0.52rem; grid-template-columns: auto minmax(0, 1fr); margin: 0.35rem 0.5rem 1.4rem; text-decoration: none; }
.workspace-layout__brand svg { color: var(--accent); grid-row: span 2; }
.workspace-layout__brand span { font-size: 0.88rem; font-weight: 600; line-height: 1.15; }
.workspace-layout__brand small { color: var(--rail-muted); font-size: 0.68rem; margin-top: 0.12rem; }
.workspace-layout__account { align-items: center; border-top: 1px solid var(--line); display: grid; gap: 0.65rem; grid-template-columns: minmax(0, 1fr) auto; margin: auto 0.3rem 0; padding: 1rem 0.25rem 0.1rem; }
.workspace-layout__profile { align-items: center; border-radius: var(--radius-sm); display: grid; gap: 0.65rem; grid-template-columns: auto minmax(0, 1fr); min-width: 0; padding: 0.2rem; text-decoration: none; }
.workspace-layout__profile:hover { background: var(--rail-hover); }
.workspace-layout__avatar { align-items: center; background: var(--surface-hover); border-radius: 50%; color: var(--text-primary); display: inline-flex; font-size: 0.78rem; font-weight: 600; height: 2rem; justify-content: center; width: 2rem; }
.workspace-layout__identity { display: grid; min-width: 0; }
.workspace-layout__identity strong, .workspace-layout__identity small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-layout__identity strong { color: var(--rail-text); font-size: 0.8rem; }
.workspace-layout__identity small { color: var(--rail-muted); font-size: 0.68rem; }
.workspace-layout__account button { align-items: center; border-radius: var(--radius-sm); color: var(--rail-muted); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.workspace-layout__account button:hover { background: var(--rail-hover); color: var(--rail-text); }
.workspace-layout__main { display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100dvh; min-width: 0; overflow: hidden; }
.workspace-layout__header { align-items: center; background: var(--surface-glass); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 3.55rem; padding: 0.55rem clamp(1.25rem, 3vw, 2.5rem); position: sticky; top: 0; z-index: 4; }
.workspace-layout__header p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; margin: 0 0 0.18rem; }
.workspace-layout__header h1 { font-size: 1rem; font-weight: 600; letter-spacing: 0; margin: 0; }
.workspace-layout__header-actions { align-items: center; display: inline-flex; gap: 0.9rem; }
.workspace-layout__theme { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-pill); color: var(--text-secondary); display: inline-flex; height: 2.1rem; justify-content: center; transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast); width: 2.1rem; }
.workspace-layout__theme:hover { background: var(--surface-hover); border-color: var(--line-strong); color: var(--text-primary); }
.workspace-layout__status { align-items: center; color: var(--status-success-text); display: inline-flex; font-size: 0.76rem; font-weight: 600; gap: 0.35rem; }
.workspace-layout__status--degraded { color: var(--status-danger-text); }
.workspace-layout__content { height: 100%; min-height: 0; overflow: hidden; width: 100%; }
.workspace-layout__mobile-nav { display: none; }
@media (max-width: 760px) { .workspace-layout { display: block; padding-bottom: 4.75rem; } .workspace-layout__rail { display: none; } .workspace-layout__header { min-height: 4.25rem; padding: 0.75rem 1rem; } .workspace-layout__header h1 { font-size: 1.05rem; } .workspace-layout__status { font-size: 0.7rem; } .workspace-layout__content { padding: 1rem; } .workspace-layout__mobile-nav { background: var(--rail); border-top: 1px solid var(--line); bottom: 0; display: block; left: 0; padding: 0.25rem 0.35rem calc(0.25rem + env(safe-area-inset-bottom)); position: fixed; right: 0; z-index: 10; } .workspace-layout__mobile-nav :deep(.workspace-navigation) { display: grid; gap: 0.15rem; grid-template-columns: repeat(6, 1fr); } .workspace-layout__mobile-nav :deep(.workspace-navigation__link) { border-radius: 0.45rem; flex-direction: column; font-size: 0.66rem; gap: 0.2rem; justify-content: center; min-height: 3.85rem; padding: 0.3rem; } }
</style>

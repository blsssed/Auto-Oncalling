<script setup lang="ts">
import { Activity, BookOpen, Cable, Gauge, MessageSquare, UserRound } from "lucide-vue-next";
import { computed } from "vue";

const props = defineProps<{
  readonly activePath: string;
  /** 移动端底栏的紧凑形态：渲染 6 个平铺入口（含个人中心），不带子导航与插槽。 */
  readonly compact?: boolean;
}>();

const entries = [
  { icon: MessageSquare, label: "对话", to: "/chat", caption: "智能问答与 RAG 检索" },
  { icon: BookOpen, label: "知识库", to: "/knowledge", caption: "文档、索引与引用" },
  { icon: Gauge, label: "监控中心", to: "/monitor/metrics", compactLabel: "监控", caption: "Prometheus 指标查询" },
  { icon: Activity, label: "AI 运维中心", to: "/aiops", compactLabel: "运维", caption: "告警、诊断、案例、历史" },
  { icon: Cable, label: "工具连接（MCP）", to: "/mcp", compactLabel: "工具", caption: "Agent 工具来源" },
  { icon: UserRound, label: "个人中心", to: "/profile", compactLabel: "我的", compactOnly: true }
] as const;

const visibleEntries = computed(() =>
  entries.filter((entry) => !("compactOnly" in entry && entry.compactOnly) || props.compact === true)
);

const monitorSubEntries = [
  { label: "Prometheus 指标监控", to: "/monitor/metrics" },
  { label: "数据源管理", to: "/monitor/sources" }
] as const;

function isActive(activePath: string, to: string): boolean {
  if (activePath === to) return true;
  // 分组头在整个分组路径下保持高亮：AI 运维中心覆盖 /aiops/*，监控中心覆盖 /monitor/*，
  // 个人中心覆盖 /profile/*（桌面端经头像进入，紧凑底栏直接可达）。
  if (to === "/aiops") return activePath.startsWith("/aiops/");
  if (to === "/monitor/metrics") return activePath.startsWith("/monitor/");
  if (to === "/profile") return activePath.startsWith("/profile");
  return false;
}
</script>

<template>
  <nav class="workspace-navigation" aria-label="工作区导航">
    <template v-for="entry in visibleEntries" :key="entry.to">
      <RouterLink
        :to="entry.to"
        class="workspace-navigation__link"
        :class="{ 'workspace-navigation__link--active': isActive(activePath, entry.to) }"
        :aria-current="isActive(activePath, entry.to) ? (activePath === entry.to ? 'page' : 'true') : undefined"
      >
        <component :is="entry.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
        <span class="workspace-navigation__text">
          <span class="workspace-navigation__label">{{ "compactLabel" in entry && compact ? entry.compactLabel : entry.label }}</span>
          <span v-if="!compact && 'caption' in entry" class="workspace-navigation__caption">{{ entry.caption }}</span>
        </span>
      </RouterLink>
      <div v-if="!compact && entry.to === '/monitor/metrics'" class="workspace-navigation__sub">
        <RouterLink
          v-for="sub in monitorSubEntries"
          :key="sub.to"
          :to="sub.to"
          class="workspace-navigation__sub-link"
          :class="{ 'workspace-navigation__sub-link--active': activePath === sub.to }"
          :aria-current="activePath === sub.to ? 'page' : undefined"
        >
          {{ sub.label }}
        </RouterLink>
      </div>
      <slot v-if="entry.to === '/chat' && activePath === '/chat'" name="chat-history" />
    </template>
  </nav>
</template>

<style scoped>
.workspace-navigation { display: grid; gap: 0.15rem; }
.workspace-navigation__link { align-items: center; border-radius: var(--radius-sm); color: var(--rail-muted); display: flex; font-size: 0.84rem; font-weight: 500; gap: 0.62rem; min-height: 2.4rem; padding: 0.32rem 0.65rem; text-decoration: none; transition: background var(--transition-fast), color var(--transition-fast); }
.workspace-navigation__link:hover { background: var(--rail-hover); color: var(--rail-text); }
.workspace-navigation__link--active { background: var(--rail-active); color: var(--rail-text); font-weight: 600; }
.workspace-navigation__link--active svg { color: var(--accent-strong); }
.workspace-navigation__text { display: grid; gap: 0.08rem; min-width: 0; }
.workspace-navigation__label { line-height: 1.2; }
.workspace-navigation__caption { color: var(--rail-muted); font-size: 0.66rem; font-weight: 400; line-height: 1.3; opacity: 0.8; }
.workspace-navigation__sub { display: grid; gap: 0.1rem; margin: 0.1rem 0 0.2rem; }
.workspace-navigation__sub-link { border-left: 2px solid var(--line-strong); color: var(--rail-muted); font-size: 0.76rem; font-weight: 500; margin-left: 1.55rem; min-height: 2rem; padding: 0 0.65rem; text-decoration: none; transition: background var(--transition-fast), color var(--transition-fast); }
.workspace-navigation__sub-link:hover { background: var(--rail-hover); color: var(--rail-text); }
.workspace-navigation__sub-link--active { border-left-color: var(--accent); color: var(--accent-strong); font-weight: 600; }
</style>

<script setup lang="ts">
import { Activity, BellRing, FolderOpen, History, LayoutDashboard } from "lucide-vue-next";
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const entries = [
  { label: "总览", icon: LayoutDashboard, to: "/aiops/overview" },
  { label: "诊断", icon: Activity, to: "/aiops" },
  { label: "告警", icon: BellRing, to: "/aiops/alerts" },
  { label: "案例", icon: FolderOpen, to: "/aiops/cases" },
  { label: "历史", icon: History, to: "/aiops/history" }
] as const;

const activePath = computed(() => route.path);
</script>

<template>
  <nav class="aiops-sub-nav" aria-label="AI 运维中心导航">
    <RouterLink
      v-for="entry in entries"
      :key="entry.to"
      :to="entry.to"
      class="aiops-sub-nav__link"
      :class="{ 'aiops-sub-nav__link--active': activePath === entry.to }"
      :aria-current="activePath === entry.to ? 'page' : undefined"
    >
      <component :is="entry.icon" :size="15" stroke-width="1.8" aria-hidden="true" />
      {{ entry.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.aiops-sub-nav { align-items: stretch; background: var(--surface-raised); border-bottom: 1px solid var(--line); display: flex; gap: 1.35rem; overflow-x: auto; padding: 0 clamp(0.9rem, 2.4vw, 1.6rem); scrollbar-width: none; }
.aiops-sub-nav::-webkit-scrollbar { display: none; }
.aiops-sub-nav__link { align-items: center; color: var(--text-secondary); display: inline-flex; flex: none; font-size: 0.8rem; font-weight: 500; gap: 0.38rem; min-height: 2.5rem; padding: 0 0.1rem; position: relative; text-decoration: none; transition: color var(--transition-fast); white-space: nowrap; }
.aiops-sub-nav__link:hover { color: var(--text-primary); }
.aiops-sub-nav__link--active { color: var(--text-primary); font-weight: 600; }
.aiops-sub-nav__link--active::after { background: var(--accent-solid); border-radius: 2px 2px 0 0; bottom: -1px; content: ""; height: 2px; left: 0; position: absolute; right: 0; }
@media (max-width: 520px) { .aiops-sub-nav { gap: 0.95rem; padding: 0 0.85rem; } .aiops-sub-nav__link { font-size: 0.76rem; gap: 0.3rem; } }
</style>

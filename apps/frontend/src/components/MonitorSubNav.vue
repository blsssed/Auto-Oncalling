<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const entries = [
  { label: "Prometheus 指标监控", to: "/monitor/metrics" },
  { label: "数据源管理", to: "/monitor/sources" }
] as const;

const activePath = computed(() => route.path);
</script>

<template>
  <nav class="monitor-sub-nav" aria-label="监控中心子导航">
    <RouterLink
      v-for="entry in entries"
      :key="entry.to"
      :to="entry.to"
      class="monitor-sub-nav__link"
      :class="{ 'monitor-sub-nav__link--active': activePath === entry.to }"
      :aria-current="activePath === entry.to ? 'page' : undefined"
    >
      {{ entry.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.monitor-sub-nav { border-bottom: 1px solid var(--line); display: none; gap: 0.2rem; overflow-x: auto; padding: 0.45rem 0.75rem; }
.monitor-sub-nav__link { border-radius: var(--radius-sm); color: var(--text-tertiary); flex: none; font-size: 0.78rem; font-weight: 600; padding: 0.4rem 0.75rem; text-decoration: none; white-space: nowrap; }
.monitor-sub-nav__link:hover { background: var(--surface-hover); color: var(--text-primary); }
.monitor-sub-nav__link--active { background: var(--accent-soft); color: var(--accent-strong); }
@media (max-width: 760px) { .monitor-sub-nav { display: flex; } }
</style>

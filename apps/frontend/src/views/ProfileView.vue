<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const entries = [
  { label: "模型配置", to: "/profile/model" },
  { label: "个人信息", to: "/profile/info" },
  { label: "关于", to: "/profile/about" }
] as const;

const activePath = computed(() => route.path);
</script>

<template>
  <section class="profile-view" aria-label="个人中心">
    <nav class="profile-view__menu" aria-label="个人中心菜单">
      <RouterLink
        v-for="entry in entries"
        :key="entry.to"
        :to="entry.to"
        class="profile-view__link"
        :class="{ 'profile-view__link--active': activePath === entry.to }"
        :aria-current="activePath === entry.to ? 'page' : undefined"
      >
        {{ entry.label }}
      </RouterLink>
    </nav>
    <div class="profile-view__content">
      <RouterView />
    </div>
  </section>
</template>

<style scoped>
.profile-view { background: var(--surface-raised); display: grid; grid-template-columns: 10.5rem minmax(0, 1fr); height: 100%; min-height: 0; }
.profile-view__menu { border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 0.2rem; overflow-y: auto; padding: 1.1rem 0.7rem; }
.profile-view__link { border-radius: var(--radius-sm); color: var(--text-tertiary); font-size: 0.82rem; font-weight: 500; min-height: 2rem; padding: 0 0.6rem; text-decoration: none; transition: background var(--transition-fast), color var(--transition-fast); display: flex; align-items: center; }
.profile-view__link:hover { background: var(--surface-hover); color: var(--text-primary); }
.profile-view__link--active { background: var(--accent-soft); color: var(--accent-strong); font-weight: 600; }
.profile-view__content { min-height: 0; overflow-y: auto; padding: 0.85rem clamp(1rem, 3vw, 2rem); }
@media (max-width: 760px) { .profile-view { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); } .profile-view__menu { border-bottom: 1px solid var(--line); border-right: 0; display: flex; flex-direction: row; overflow-x: auto; padding: 0.45rem 0.75rem; } .profile-view__link { flex: none; min-height: 2rem; padding: 0.35rem 0.75rem; white-space: nowrap; } .profile-view__content { padding: 1rem; } }
@media (prefers-reduced-motion: reduce) { .profile-view__link { transition: none; } }
</style>

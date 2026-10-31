<script setup lang="ts">
import { ArrowRight } from "lucide-vue-next";

withDefaults(
  defineProps<{
    readonly actionLabel?: string;
    readonly actionTo?: string;
    readonly detail?: string;
    readonly title: string;
  }>(),
  { actionLabel: "", actionTo: "", detail: "" }
);
</script>

<template>
  <section class="empty-state" aria-live="polite">
    <svg class="empty-state__art" viewBox="0 0 104 76" aria-hidden="true" focusable="false">
      <circle class="empty-state__ring empty-state__ring--outer" cx="34" cy="38" r="27" />
      <circle class="empty-state__ring" cx="34" cy="38" r="16" />
      <circle class="empty-state__dot" cx="34" cy="38" r="5" />
      <path class="empty-state__line" d="M62 29h30M62 39h24M62 49h28" />
    </svg>
    <div class="empty-state__copy">
      <h2>{{ title }}</h2>
      <p v-if="detail">{{ detail }}</p>
      <RouterLink v-if="actionLabel && actionTo" class="empty-state__action" :to="actionTo">
        {{ actionLabel }}
        <ArrowRight :size="14" aria-hidden="true" />
      </RouterLink>
      <slot name="action" />
    </div>
  </section>
</template>

<style scoped>
.empty-state {
  align-items: center;
  border-top: 1px solid var(--line);
  display: flex;
  gap: 1.1rem;
  max-width: 46rem;
  padding: 1.6rem 0;
}

.empty-state__art {
  flex: none;
  height: 4.75rem;
  width: 6.5rem;
}

.empty-state__ring {
  fill: none;
  stroke: var(--accent-border);
  stroke-width: 1.5;
}

.empty-state__ring--outer {
  stroke: var(--accent-soft);
  stroke-dasharray: 3 5;
}

.empty-state__dot {
  fill: var(--accent);
}

.empty-state__line {
  stroke: var(--line-strong);
  stroke-linecap: round;
  stroke-width: 3;
}

.empty-state__copy {
  display: grid;
  gap: 0.45rem;
  min-width: 0;
}

h2 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

p {
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
  max-width: 34rem;
}

.empty-state__action {
  align-items: center;
  color: var(--accent-strong);
  display: inline-flex;
  font-size: 0.8rem;
  font-weight: 600;
  gap: 0.3rem;
  text-decoration: none;
  width: fit-content;
}

.empty-state__action:hover {
  text-decoration: underline;
}

@media (max-width: 560px) {
  .empty-state { align-items: flex-start; flex-direction: column; gap: 0.7rem; }
  .empty-state__art { height: 3.5rem; width: 4.8rem; }
}
</style>

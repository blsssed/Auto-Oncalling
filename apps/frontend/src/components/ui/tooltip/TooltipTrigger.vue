<script setup lang="ts">
import type { TooltipTriggerProps } from "reka-ui"
import { TooltipTrigger } from "reka-ui"

const props = defineProps<TooltipTriggerProps>()

const forwardedProps = props as TooltipTriggerProps
</script>

<template>
  <TooltipTrigger
    data-slot="tooltip-trigger"
    v-bind="forwardedProps"
  >
    <slot />
  </TooltipTrigger>
</template>

<script setup lang="ts">
import type { TooltipProviderProps } from "reka-ui"
import { TooltipProvider } from "reka-ui"

const props = withDefaults(defineProps<TooltipProviderProps>(), {
  delayDuration: 0,
})

const forwardedProps = props as TooltipProviderProps
</script>

<template>
  <TooltipProvider v-bind="forwardedProps">
    <slot />
  </TooltipProvider>
</template>

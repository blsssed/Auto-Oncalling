<script setup lang="ts">
import type { SelectValueProps } from "reka-ui"
import { SelectValue } from "reka-ui"

const props = defineProps<SelectValueProps>()

const forwardedProps = props as SelectValueProps
</script>

<template>
  <SelectValue
    data-slot="select-value"
    v-bind="forwardedProps"
  >
    <slot />
  </SelectValue>
</template>

<script setup lang="ts">
import type { SelectItemTextProps } from "reka-ui"
import { SelectItemText } from "reka-ui"

const props = defineProps<SelectItemTextProps>()

const forwardedProps = props as SelectItemTextProps
</script>

<template>
  <SelectItemText
    data-slot="select-item-text"
    v-bind="forwardedProps"
  >
    <slot />
  </SelectItemText>
</template>

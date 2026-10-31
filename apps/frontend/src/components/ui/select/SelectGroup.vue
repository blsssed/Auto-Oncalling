<script setup lang="ts">
import type { SelectGroupProps } from "reka-ui"
import { SelectGroup } from "reka-ui"

const props = defineProps<SelectGroupProps>()

const forwardedProps = props as SelectGroupProps
</script>

<template>
  <SelectGroup
    data-slot="select-group"
    v-bind="forwardedProps"
  >
    <slot />
  </SelectGroup>
</template>

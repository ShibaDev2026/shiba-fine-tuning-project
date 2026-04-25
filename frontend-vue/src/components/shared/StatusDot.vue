<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  state?: 'active' | 'inactive' | 'pending' | 'error'
}
const props = withDefaults(defineProps<Props>(), { state: 'inactive' })

const COLORS: Record<string, string> = {
  active:   '#00e676',
  inactive: '#3a4454',
  pending:  '#ffab40',
  error:    '#ff5252',
}

const style = computed(() => ({
  background: COLORS[props.state] ?? COLORS.inactive,
  animation: (props.state === 'active' || props.state === 'pending')
    ? 'pulse-dot 2s ease-in-out infinite'
    : 'none',
}))
</script>

<template>
  <span class="inline-block w-2 h-2 rounded-full shrink-0" :style="style" />
</template>

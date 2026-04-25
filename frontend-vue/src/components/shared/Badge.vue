<script setup lang="ts">
// Badge：依 type 從預設色對映取樣；未命中則退 neutral
interface Props {
  type?: string
}
const props = withDefaults(defineProps<Props>(), { type: 'neutral' })

const MAP: Record<string, { bg: string; color: string }> = {
  approved:        { bg: '#00251a', color: '#00e676' },
  rejected:        { bg: '#2c0000', color: '#ff5252' },
  needs_review:    { bg: '#2c1800', color: '#ffab40' },
  pending:         { bg: '#00293d', color: '#40c4ff' },
  raw:             { bg: '#21262f', color: '#8a97a8' },
  done:            { bg: '#00251a', color: '#00e676' },
  gate_rejected:   { bg: '#2c0000', color: '#ff5252' },
  failed:          { bg: '#2c0000', color: '#ff5252' },
  local:           { bg: '#2a2000', color: '#f5c518' },
  claude:          { bg: '#1e1430', color: '#c084fc' },
  neutral:         { bg: '#21262f', color: '#8a97a8' },
  info:            { bg: '#00293d', color: '#40c4ff' },
  warning:         { bg: '#2c1800', color: '#ffab40' },
  git_ops:         { bg: '#2a2000', color: '#f5c518' },
  terminal_ops:    { bg: '#00251a', color: '#00e676' },
  code_gen:        { bg: '#00293d', color: '#40c4ff' },
  debugging:       { bg: '#2c0000', color: '#ff5252' },
  architecture:    { bg: '#1e1430', color: '#c084fc' },
  knowledge_qa:    { bg: '#00201c', color: '#00bfa5' },
  fine_tuning_ops: { bg: '#2c1800', color: '#ffab40' },
}

import { computed } from 'vue'
const style = computed(() => {
  const m = MAP[props.type] ?? MAP.neutral
  return { background: m.bg, color: m.color }
})
</script>

<template>
  <span
    class="inline-flex items-center font-mono text-xs px-[7px] py-[2px] rounded-sm font-semibold tracking-wide"
    :style="style"
  >
    <slot />
  </span>
</template>

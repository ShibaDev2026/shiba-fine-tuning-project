<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  used: number
  limit: number | null | undefined
  label: string
  sublabel?: string
}
const props = defineProps<Props>()

const pct = computed(() =>
  props.limit ? Math.min(100, Math.round((props.used / props.limit) * 100)) : 0
)
const color = computed(() => {
  if (!props.limit) return '#00e676'
  const p = pct.value
  return p < 50 ? '#00e676' : p < 80 ? '#ffab40' : '#ff5252'
})
const remaining = computed(() =>
  props.limit != null ? Math.max(0, props.limit - props.used) : null
)
</script>

<template>
  <div class="flex flex-col gap-[5px]">
    <div class="flex justify-between font-mono text-xs" style="color: #8a97a8">
      <span>{{ label }}</span>
      <span v-if="remaining !== null" :style="{ color }">
        {{ remaining }}/{{ limit }} 剩餘
      </span>
      <span v-else style="color: #00e676">∞ unlimited</span>
    </div>
    <div class="w-full h-[5px] rounded-full overflow-hidden" style="background:#2c333e">
      <div
        class="h-full rounded-full transition-all duration-300"
        :style="{ width: `${pct}%`, background: color }"
      />
    </div>
    <div v-if="sublabel" class="font-mono" style="font-size:10px; color:#505c6e">
      {{ sublabel }}
    </div>
  </div>
</template>

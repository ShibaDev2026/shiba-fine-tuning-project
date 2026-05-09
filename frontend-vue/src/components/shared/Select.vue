<script setup lang="ts">
import { computed } from 'vue'

// 共用 dropdown：支援 disabled options + tooltip + label
export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
  tooltip?: string  // 滑鼠 hover 顯示（disabled 時尤其重要：說明為什麼不能選）
}

interface Props {
  modelValue: string
  options: SelectOption[]
  label?: string       // 左側顯示文字（如「分類器：」）
  disabled?: boolean   // 整個 select 停用
  width?: string       // CSS width，預設 auto
}
const props = withDefaults(defineProps<Props>(), {
  label: '',
  disabled: false,
  width: 'auto',
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'change', v: string): void
}>()

function onChange(ev: Event) {
  const v = (ev.target as HTMLSelectElement).value
  emit('update:modelValue', v)
  emit('change', v)
}

const wrapperStyle = computed(() => ({ width: props.width }))
</script>

<template>
  <span class="inline-flex items-center font-mono" style="gap:6px; font-size:11px" :style="wrapperStyle">
    <span v-if="label" style="color:#505c6e">{{ label }}</span>
    <select
      :value="modelValue"
      :disabled="disabled"
      @change="onChange"
      class="font-mono"
      style="background:#21262f; color:#f5c518; border:1px solid #2c333d; border-radius:6px; padding:3px 8px; font-size:11px; outline:none; cursor:pointer"
      :style="{ opacity: disabled ? 0.5 : 1 }"
    >
      <option
        v-for="opt in options"
        :key="opt.value"
        :value="opt.value"
        :disabled="opt.disabled"
        :title="opt.tooltip ?? ''"
        :style="{ color: opt.disabled ? '#505c6e' : '#f5c518' }"
      >
        {{ opt.label }}{{ opt.disabled ? ' (不可用)' : '' }}
      </option>
    </select>
  </span>
</template>

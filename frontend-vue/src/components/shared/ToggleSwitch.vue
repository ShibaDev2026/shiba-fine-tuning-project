<script setup lang="ts">
// 共用 toggle 開關：on/off 兩態 + 自訂 label
interface Props {
  modelValue: boolean
  onLabel?: string    // ON 狀態文字（預設 "online"）
  offLabel?: string   // OFF 狀態文字（預設 "offline"）
  disabled?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  onLabel: 'online',
  offLabel: 'offline',
  disabled: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'change', v: boolean): void
}>()

function toggle() {
  if (props.disabled) return
  const next = !props.modelValue
  emit('update:modelValue', next)
  emit('change', next)
}
</script>

<template>
  <button
    type="button"
    :disabled="disabled"
    @click="toggle"
    class="inline-flex items-center font-mono"
    style="gap:6px; font-size:11px; padding:3px 10px; border-radius:14px; border:1px solid; background:transparent; cursor:pointer; transition:all 0.15s"
    :style="{
      borderColor: modelValue ? '#00e676' : '#ff5252',
      opacity: disabled ? 0.5 : 1,
      cursor: disabled ? 'not-allowed' : 'pointer',
    }"
  >
    <span
      style="display:inline-block; width:8px; height:8px; border-radius:50%"
      :style="{ background: modelValue ? '#00e676' : '#ff5252' }"
    />
    <span :style="{ color: modelValue ? '#00e676' : '#ff5252' }">
      {{ modelValue ? onLabel : offLabel }}
    </span>
  </button>
</template>

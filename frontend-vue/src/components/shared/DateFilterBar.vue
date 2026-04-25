<script setup lang="ts">
// 支援 today / 7d / all / custom 四模式，quickBg 控制 active 色（Router 黃 / Memory 藍）
export type DateMode = 'today' | '7d' | 'all' | 'custom'

interface Props {
  mode: DateMode
  dateFrom: string
  dateTo: string
  quickBg?: string
}
const props = withDefaults(defineProps<Props>(), { quickBg: '#40c4ff' })

const emit = defineEmits<{
  (e: 'update:mode', v: DateMode): void
  (e: 'update:dateFrom', v: string): void
  (e: 'update:dateTo', v: string): void
  (e: 'change', payload: { mode: DateMode; from: string; to: string }): void
}>()

const QUICK_OPTS: { label: string; value: DateMode }[] = [
  { label: '今日',  value: 'today' },
  { label: '近7天', value: '7d' },
  { label: '全部',  value: 'all' },
]

function pickMode(v: DateMode) {
  emit('update:mode', v)
  emit('change', { mode: v, from: props.dateFrom, to: props.dateTo })
}

function pickDate(which: 'from' | 'to', val: string) {
  const from = which === 'from' ? val : props.dateFrom
  const to   = which === 'to'   ? val : props.dateTo
  if (which === 'from') emit('update:dateFrom', val)
  else                  emit('update:dateTo', val)
  emit('update:mode', 'custom')
  emit('change', { mode: 'custom', from, to })
}
</script>

<template>
  <div class="flex items-center flex-wrap" style="gap:8px">
    <button
      v-for="o in QUICK_OPTS"
      :key="o.value"
      @click="pickMode(o.value)"
      class="font-mono border-0 cursor-pointer"
      style="padding:3px 10px; border-radius:6px; font-size:11px"
      :style="{
        background: mode === o.value ? quickBg : '#21262f',
        color:       mode === o.value ? '#12151b' : '#8a97a8',
      }"
    >
      {{ o.label }}
    </button>

    <span class="font-mono" style="color:#21262f; font-size:11px">|</span>
    <span class="font-mono" style="font-size:10px; color:#505c6e">自訂：</span>

    <input
      type="date"
      :value="dateFrom"
      @input="(e) => pickDate('from', (e.target as HTMLInputElement).value)"
      class="font-mono border-0 cursor-pointer"
      style="background:#21262f; border-radius:5px; padding:3px 7px; font-size:11px; color:#edf0f4; color-scheme:dark"
    />
    <span style="color:#505c6e; font-size:11px">—</span>
    <input
      type="date"
      :value="dateTo"
      @input="(e) => pickDate('to', (e.target as HTMLInputElement).value)"
      class="font-mono border-0 cursor-pointer"
      style="background:#21262f; border-radius:5px; padding:3px 7px; font-size:11px; color:#edf0f4; color-scheme:dark"
    />
  </div>
</template>

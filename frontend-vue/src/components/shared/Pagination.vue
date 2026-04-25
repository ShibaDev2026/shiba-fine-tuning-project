<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  total: number
  pageSize: number
  current: number
  activeColor?: string  // PhaseRouter #f5c518，PhaseMemory #40c4ff
}
const props = withDefaults(defineProps<Props>(), { activeColor: '#40c4ff' })

const emit = defineEmits<{
  (e: 'update:current', value: number): void
  (e: 'update:pageSize', value: number): void
}>()

const totalPages = computed(() => Math.ceil(props.total / props.pageSize))

// 產生頁碼序列（含 '…' 佔位）
const pageNums = computed(() => {
  const tp = totalPages.value
  const cur = props.current
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  const show = new Set(
    [1, tp, cur - 2, cur - 1, cur, cur + 1, cur + 2].filter(p => p >= 1 && p <= tp)
  )
  const sorted = [...show].sort((a, b) => a - b)
  const result: (number | '…')[] = []
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) result.push('…')
    result.push(sorted[i])
  }
  return result
})

const start = computed(() => (props.current - 1) * props.pageSize + 1)
const end = computed(() => Math.min(props.current * props.pageSize, props.total))

function btnStyle(active: boolean, disabled: boolean) {
  return {
    minWidth: '28px',
    height: '26px',
    padding: '0 6px',
    borderRadius: '5px',
    border: 'none',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'var(--font-mono, monospace)',
    fontSize: '11px',
    background: active ? props.activeColor : '#21262f',
    color: active ? '#12151b' : disabled ? '#2c333e' : '#8a97a8',
  }
}

function goto(p: number) {
  if (p < 1 || p > totalPages.value) return
  emit('update:current', p)
}
function setSize(s: number) {
  emit('update:pageSize', s)
  emit('update:current', 1)
}
</script>

<template>
  <div
    v-if="total > 0"
    class="flex items-center flex-wrap"
    style="padding:10px 16px; border-top:1px solid #21262f; justify-content:space-between; gap:12px"
  >
    <span class="font-mono shrink-0" style="font-size:11px; color:#505c6e">
      共 {{ total }} 筆 · 顯示第 {{ start }}–{{ end }} 筆
    </span>

    <div class="flex items-center flex-wrap" style="gap:4px">
      <button :style="btnStyle(false, current === 1)" :disabled="current === 1" @click="goto(current - 1)">‹</button>
      <template v-for="(p, i) in pageNums" :key="typeof p === 'number' ? p : `e${i}`">
        <span v-if="p === '…'" class="font-mono" style="color:#505c6e; font-size:11px; padding:0 3px">…</span>
        <button v-else :style="btnStyle(p === current, false)" @click="goto(p as number)">{{ p }}</button>
      </template>
      <button :style="btnStyle(false, current === totalPages)" :disabled="current === totalPages" @click="goto(current + 1)">›</button>
    </div>

    <select
      :value="pageSize"
      @change="(e) => setSize(Number((e.target as HTMLSelectElement).value))"
      class="font-mono cursor-pointer border-0"
      style="background:#21262f; border-radius:6px; padding:3px 8px; font-size:11px; color:#8a97a8; color-scheme:dark"
    >
      <option v-for="n in [10, 30, 50]" :key="n" :value="n">{{ n }} 筆</option>
    </select>
  </div>
</template>

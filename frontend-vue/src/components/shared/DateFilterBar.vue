<script setup lang="ts">
import { ref, watch } from 'vue'

export type DateMode = 'today' | '7d' | 'all' | 'custom'

interface Props {
  mode: DateMode
  dateFrom: string   // ISO yyyy-MM-dd
  dateTo: string     // ISO yyyy-MM-dd
  quickBg?: string
  allDateFrom?: string  // 傳入資料最早日期，'全部' 時填入起始欄
}
const props = withDefaults(defineProps<Props>(), { quickBg: '#40c4ff', allDateFrom: '' })

const emit = defineEmits<{
  (e: 'update:mode',     v: DateMode): void
  (e: 'update:dateFrom', v: string):   void
  (e: 'update:dateTo',   v: string):   void
  (e: 'change', payload: { mode: DateMode; from: string; to: string }): void
}>()

const QUICK_OPTS: { label: string; value: DateMode }[] = [
  { label: '今日',  value: 'today' },
  { label: '近7天', value: '7d' },
  { label: '全部',  value: 'all' },
]

// ── 日期工具 ────────────────────────────────────────────
function isoToday(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function isoOffset(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function isoToDisplay(iso: string): string {
  return iso ? iso.replace(/-/g, '/') : ''
}
function parseToIso(val: string): string {
  // 接受 yyyyMMdd 或 yyyy/MM/dd
  const digits = val.replace(/\D/g, '')
  if (digits.length !== 8) return ''
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
}

// ── 本地文字狀態（顯示用 yyyy/MM/dd）────────────────────
const inputFrom = ref(isoToDisplay(props.dateFrom))
const inputTo   = ref(isoToDisplay(props.dateTo))

// 外部 prop 改變時同步（點快捷按鈕後 parent 更新 prop）
watch(() => props.dateFrom, v => { inputFrom.value = isoToDisplay(v) })
watch(() => props.dateTo,   v => { inputTo.value   = isoToDisplay(v) })

// ── 快捷按鈕：點擊後計算對應日期並 emit ─────────────────
function pickMode(v: DateMode) {
  const t = isoToday()
  let from = ''
  const to  = t
  if (v === 'today')  from = t
  else if (v === '7d') from = isoOffset(-6)
  else if (v === 'all') from = props.allDateFrom || ''

  emit('update:mode', v)
  emit('update:dateFrom', from)
  emit('update:dateTo', to)
  emit('change', { mode: v, from, to })
}

// ── 文字輸入：8 位數字時自動格式化為 yyyy/MM/dd ──────────
function onTyping(which: 'from' | 'to', raw: string) {
  const digits = raw.replace(/\D/g, '')
  const formatted = digits.length >= 8
    ? `${digits.slice(0, 4)}/${digits.slice(4, 6)}/${digits.slice(6, 8)}`
    : raw
  if (which === 'from') inputFrom.value = formatted
  else inputTo.value = formatted
}

// ── blur / Enter：解析並 emit，無效時還原 ────────────────
function commit(which: 'from' | 'to') {
  const raw = which === 'from' ? inputFrom.value : inputTo.value
  const iso = parseToIso(raw)
  if (!iso) {
    if (which === 'from') inputFrom.value = isoToDisplay(props.dateFrom)
    else inputTo.value = isoToDisplay(props.dateTo)
    return
  }
  const from = which === 'from' ? iso : props.dateFrom
  const to   = which === 'to'   ? iso : props.dateTo
  if (which === 'from') emit('update:dateFrom', iso)
  else emit('update:dateTo', iso)
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
    <span class="font-mono" style="font-size:10px; color:#505c6e">起始日期：</span>

    <input
      type="text"
      :value="inputFrom"
      placeholder="yyyy/mm/dd"
      @input="(e) => onTyping('from', (e.target as HTMLInputElement).value)"
      @blur="commit('from')"
      @keydown.enter="commit('from')"
      class="font-mono border-0 cursor-pointer"
      style="background:#21262f; border-radius:5px; padding:3px 7px; font-size:11px; color:#edf0f4; width:90px"
    />
    <span style="color:#505c6e; font-size:11px">至</span>
    <input
      type="text"
      :value="inputTo"
      placeholder="yyyy/mm/dd"
      @input="(e) => onTyping('to', (e.target as HTMLInputElement).value)"
      @blur="commit('to')"
      @keydown.enter="commit('to')"
      class="font-mono border-0 cursor-pointer"
      style="background:#21262f; border-radius:5px; padding:3px 7px; font-size:11px; color:#edf0f4; width:90px"
    />
  </div>
</template>

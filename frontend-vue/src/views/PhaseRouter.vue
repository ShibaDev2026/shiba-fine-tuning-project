<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api/client'
import { buildDateQS, fmtDT } from '../api/dateFilter'
import type { Column } from '../components/shared/DataTable.vue'
import type { DateMode } from '../components/shared/DateFilterBar.vue'
import SectionHeader  from '../components/shared/SectionHeader.vue'
import StatCard       from '../components/shared/StatCard.vue'
import DataTable      from '../components/shared/DataTable.vue'
import DetailPanel    from '../components/shared/DetailPanel.vue'
import Btn            from '../components/shared/Btn.vue'
import Pagination     from '../components/shared/Pagination.vue'
import DateFilterBar  from '../components/shared/DateFilterBar.vue'
import RouterDonut    from '../components/RouterDonut.vue'

// ── 型別 ────────────────────────────────────────────────
interface Decision {
  id: number
  created_at: string
  classification: string | null
  reason: string | null
  latency_ms: number | null
  tokens_prompt: number | null
  tokens_response: number | null
  user_accepted: 0 | 1 | null
  session_id: string | null
  prompt_hash: string | null
  local_output: string | null
}
interface Stats {
  total_decisions: number
  local_count: number
  claude_count: number
  local_pct: number
  claude_pct: number
  qwen_error_count: number
  acceptance_rate_7d: number | null
  avg_latency_ms: number | null
  avg_prompt_tokens: number | null
  last_decision_at: string | null
}
interface SysStatus {
  ollama_online: boolean
  classifier_model: string | null
  local_model: string | null
}
interface CtxMessage {
  role: 'user' | 'assistant'
  content: string | null
  has_tool_use?: boolean
}
interface Context {
  decision_at?: string
  messages: CtxMessage[]
  error?: string
}

// ── 決策類型說明 ────────────────────────────────────────
const DECISION_DESC: Record<string, { color: string; label: string; desc: string }> = {
  local:  { color: '#f5c518', label: 'Local 建議注入',   desc: 'Gemma 判定本地可處理。Qwen 先跑，建議注入 Claude 上下文，Claude 仍執行最終回應。' },
  claude: { color: '#c084fc', label: 'Claude 直接處理', desc: 'Gemma 判定需 Claude 完整能力，無本地介入，直接由 Claude 回應。' },
}

// ── 事件類型說明 ────────────────────────────────────────
const EVENT_DESC: Record<string, { color: string; label: string; desc: string }> = {
  fallback:        { color: '#ff9800', label: '分類器 Fallback',  desc: 'Ollama 離線或 Gemma 解析失敗，classifier.py 強制走 Claude，無事件分類' },
  qwen_error:      { color: '#ff5252', label: 'Qwen 失敗',        desc: 'Gemma 判定 local，但 Qwen 執行失敗，已 fallback 至 Claude' },
  git_ops:         { color: '#40c4ff', label: 'Git 操作',         desc: 'commit / branch / merge / rebase' },
  terminal_ops:    { color: '#69f0ae', label: '終端機指令',       desc: 'shell / 腳本 / 路徑 / 環境變數' },
  code_gen:        { color: '#f5c518', label: '程式碼生成',       desc: '新增或修改程式碼、函式、模組' },
  debugging:       { color: '#ff7043', label: '除錯',             desc: '錯誤排查、測試修復、stack trace' },
  architecture:    { color: '#e040fb', label: '架構設計',         desc: '系統設計、技術選型、模組拆分' },
  knowledge_qa:    { color: '#8a97a8', label: '知識問答',         desc: '概念解釋、文件查詢、技術說明' },
  fine_tuning_ops: { color: '#00e676', label: 'Fine-tuning 操作', desc: '訓練 / 評分 / 資料集 / Adapter' },
}

// ── 狀態 ────────────────────────────────────────────────
const selected      = ref<Decision | null>(null)
const decisions     = ref<Decision[]>([])
const stats         = ref<Stats | null>(null)
const sysStatus     = ref<SysStatus | null>(null)
const statusLoading = ref(true)
const loading       = ref(true)
const error         = ref<string | null>(null)

const dateMode    = ref<DateMode>('today')
const dateFrom    = ref('')
const dateTo      = ref('')
const pageSize    = ref(10)
const currentPage = ref(1)

const legendOpen = ref(false)
const ctx        = ref<Context | null>(null)
const ctxLoading = ref(false)

// 切換篩選或換頁大小時重設回第一頁
watch([decisions, pageSize], () => { currentPage.value = 1 })

// ── API 呼叫 ────────────────────────────────────────────
async function fetchDecisions(mode: DateMode, from: string, to: string) {
  const qs = buildDateQS(mode, from, to)
  return api.get<Decision[]>(`/router/decisions?limit=500${qs ? '&' + qs : ''}`)
}
async function fetchData(mode = dateMode.value, from = dateFrom.value, to = dateTo.value) {
  loading.value = true
  error.value = null
  try {
    const [dec, st] = await Promise.all([
      fetchDecisions(mode, from, to),
      api.get<Stats>('/router/stats'),
    ])
    decisions.value = dec
    stats.value = st
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
async function fetchStatus() {
  statusLoading.value = true
  try {
    sysStatus.value = await api.get<SysStatus>('/router/status')
  } catch {
    sysStatus.value = null
  } finally {
    statusLoading.value = false
  }
}
onMounted(() => { fetchData(); fetchStatus() })

function handleDateChange(p: { mode: DateMode; from: string; to: string }) {
  dateMode.value = p.mode
  dateFrom.value = p.from
  dateTo.value   = p.to
  fetchData(p.mode, p.from, p.to)
}

// ── 對話脈絡（選到某筆決策時才抓）────────────────────────
watch(selected, async (d) => {
  if (!d || !d.session_id) { ctx.value = null; return }
  ctxLoading.value = true
  try {
    ctx.value = await api.get<Context>(`/router/decisions/${d.id}/context`)
  } catch (e) {
    ctx.value = { error: (e as Error).message, messages: [] }
  } finally {
    ctxLoading.value = false
  }
})

async function handleAcceptance(id: number, accepted: boolean) {
  await api.put(`/router/decisions/${id}/acceptance`, { accepted })
  const val: 0 | 1 = accepted ? 1 : 0
  if (selected.value && selected.value.id === id) selected.value = { ...selected.value, user_accepted: val }
  decisions.value = decisions.value.map(d => d.id === id ? { ...d, user_accepted: val } : d)
}

// ── 衍生值 ──────────────────────────────────────────────
const paginatedDecisions = computed(() =>
  decisions.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value)
)

const total          = computed(() => stats.value?.total_decisions ?? 0)
const localCount     = computed(() => stats.value?.local_count ?? 0)
const claudeCount    = computed(() => stats.value?.claude_count ?? 0)
const localPct       = computed(() => stats.value?.local_pct ?? 0)
const claudePct      = computed(() => stats.value?.claude_pct ?? 0)
const qwenError      = computed(() => stats.value?.qwen_error_count ?? 0)
const adoptionRate7d = computed(() => {
  const r = stats.value?.acceptance_rate_7d
  return r != null ? `${Math.round(r * 100)}%` : '—'
})
const qwenFailRate   = computed(() => total.value > 0 ? `${(qwenError.value / total.value * 100).toFixed(1)}%` : '—')

const metrics = computed(() => [
  { label: '平均 Local Latency', value: stats.value?.avg_latency_ms ? `${stats.value.avg_latency_ms}ms` : '—', color: '#f5c518' },
  { label: '平均 Prompt Tokens', value: stats.value?.avg_prompt_tokens ?? '—',                                  color: '#40c4ff' },
  { label: 'Qwen 失敗率',        value: qwenFailRate.value,                                                     color: '#ff5252' },
  { label: '最後決策時間',       value: fmtDT(stats.value?.last_decision_at),                                   color: '#8a97a8' },
])

// ── DataTable 欄位（使用 slot 渲染）─────────────────────
const columns: Column[] = [
  { key: 'created_at',     label: '時間',     mono: true },
  { key: 'classification', label: '決策' },
  { key: 'reason',         label: '事件類型' },
  { key: 'latency_ms',     label: 'Latency',  mono: true },
  { key: 'tokens_prompt',  label: 'P.Tokens', mono: true },
  { key: 'user_accepted',  label: '採納' },
]

// 詳情所需元資料
const selDec = computed(() => (selected.value && DECISION_DESC[selected.value.classification ?? '']) || null)
const selEvt = computed(() => (selected.value && EVENT_DESC[selected.value.reason ?? '']) || null)

const selMeta = computed(() => {
  const s = selected.value
  if (!s) return []
  return [
    { k: '決策時間',      v: fmtDT(s.created_at) },
    { k: 'Latency',       v: s.latency_ms ? `${s.latency_ms}ms` : '— (Claude)' },
    { k: 'Prompt Tokens', v: s.tokens_prompt ?? '—' },
    { k: 'Resp Tokens',   v: s.tokens_response ?? '—' },
  ]
})
</script>

<template>
  <div class="flex-1 flex flex-col" style="min-width:0">
    <SectionHeader
      title="路由層"
      sub="Layer 0 · 建議注入模式 · Gemma 分類 → Qwen 建議注入 + 全域決策紀錄"
      accent="#f5c518"
    >
      <template #actions>
        <Btn variant="ghost" @click="fetchData(); fetchStatus()">刷新</Btn>
      </template>
    </SectionHeader>

    <!-- 系統狀態列 -->
    <div
      v-if="statusLoading"
      class="font-mono"
      style="padding:8px 14px; margin-bottom:14px; border-radius:8px; background:#191d24; border:1px solid #21262f; font-size:11px; color:#505c6e"
    >
      檢查系統狀態…
    </div>
    <div
      v-else
      class="flex items-center flex-wrap font-mono"
      style="gap:12px; padding:8px 14px; margin-bottom:14px; border-radius:8px; background:#191d24; border:1px solid #21262f; font-size:11px"
    >
      <span>
        <span :style="{ color: sysStatus?.ollama_online ? '#00e676' : '#ff5252', marginRight: '4px' }">●</span>
        <span style="color:#8a97a8">Ollama </span>
        <span :style="{ color: sysStatus?.ollama_online ? '#00e676' : '#ff5252' }">
          {{ sysStatus?.ollama_online ? 'online' : 'offline' }}
        </span>
      </span>
      <span style="color:#21262f">|</span>
      <span>
        <span style="color:#505c6e">分類器：</span>
        <span style="color:#f5c518">{{ sysStatus?.classifier_model ?? '—' }}</span>
      </span>
      <span style="color:#21262f">|</span>
      <span>
        <span style="color:#505c6e">本地：</span>
        <span style="color:#f5c518">{{ sysStatus?.local_model ?? '—' }}</span>
      </span>
      <span style="color:#21262f">|</span>
      <span>
        <span style="color:#505c6e">模式：</span>
        <span style="color:#40c4ff">建議注入</span>
      </span>
      <span v-if="!sysStatus?.ollama_online" style="color:#ff5252; margin-left:auto">⚠ Ollama 離線</span>
    </div>

    <div v-if="error" class="font-mono" style="color:#ff5252; font-size:12px; margin-bottom:8px">
      API 錯誤：{{ error }}
    </div>
    <div v-if="loading" class="font-mono" style="color:#505c6e; font-size:12px; margin-bottom:8px">
      載入中…
    </div>

    <!-- StatCards -->
    <div class="grid grid-cols-4" style="gap:10px; margin-bottom:20px">
      <StatCard label="今日決策"    :value="total" sub="sessions" />
      <StatCard label="Local 路由"  :value="`${localPct}%`"  :sub="`${localCount} 次`"  color="#f5c518" />
      <StatCard label="Claude 路由" :value="`${claudePct}%`" :sub="`${claudeCount} 次`" color="#c084fc" />
      <StatCard label="採納率"      :value="adoptionRate7d"   sub="近7天 local 採納"     color="#00e676" />
    </div>

    <!-- Donut + Metrics -->
    <div class="flex" style="gap:16px; margin-bottom:18px; align-items:flex-start">
      <div
        class="flex flex-col items-center shrink-0"
        style="background:#191d24; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04); padding:18px 20px; gap:12px"
      >
        <RouterDonut :local-pct="localPct" />
        <div class="flex" style="gap:16px">
          <div class="flex items-center font-mono" style="gap:5px; font-size:11px; color:#8a97a8">
            <div style="width:8px; height:8px; border-radius:50%; background:#f5c518" />local {{ localPct }}%
          </div>
          <div class="flex items-center font-mono" style="gap:5px; font-size:11px; color:#8a97a8">
            <div style="width:8px; height:8px; border-radius:50%; background:#c084fc" />claude {{ 100 - localPct }}%
          </div>
        </div>
      </div>
      <div class="flex-1 flex flex-col" style="gap:8px">
        <div
          v-for="m in metrics"
          :key="m.label"
          class="flex items-center justify-between"
          style="background:#191d24; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04); padding:11px 16px"
        >
          <span style="font-size:12px; color:#505c6e">{{ m.label }}</span>
          <span class="font-mono" style="font-size:15px; font-weight:600" :style="{ color: m.color }">{{ m.value }}</span>
        </div>
      </div>
    </div>

    <!-- 狀態說明圖例（可折疊）-->
    <div
      style="margin-bottom:14px; border-radius:10px; background:#191d24; border:1px solid #21262f; overflow:hidden"
    >
      <button
        @click="legendOpen = !legendOpen"
        class="w-full flex items-center justify-between font-mono border-0 cursor-pointer"
        style="padding:9px 14px; background:none; font-size:11px; color:#505c6e; text-align:left"
      >
        <span>狀態說明 · 決策類型 &amp; 事件類型</span>
        <span style="font-size:10px">{{ legendOpen ? '▲' : '▼' }}</span>
      </button>
      <div v-if="legendOpen" class="flex flex-col" style="padding:0 14px 14px; gap:14px">
        <!-- 決策類型 -->
        <div>
          <div
            class="font-mono uppercase"
            style="font-size:10px; color:#505c6e; letter-spacing:0.08em; margin-bottom:8px"
          >
            決策類型
          </div>
          <div class="flex" style="gap:10px">
            <div
              v-for="(d, k) in DECISION_DESC"
              :key="k"
              class="flex-1"
              style="background:#12151b; border-radius:8px; padding:10px 12px"
            >
              <div class="flex items-center" style="gap:8px; margin-bottom:4px">
                <span
                  class="font-mono"
                  style="padding:2px 8px; border-radius:4px; font-size:11px"
                  :style="{ background: d.color + '22', color: d.color }"
                >{{ k }}</span>
                <span style="font-size:12px; color:#edf0f4; font-weight:600">{{ d.label }}</span>
              </div>
              <div style="font-size:11px; color:#505c6e; line-height:1.5">{{ d.desc }}</div>
            </div>
          </div>
        </div>
        <!-- 事件類型 -->
        <div>
          <div
            class="font-mono uppercase"
            style="font-size:10px; color:#505c6e; letter-spacing:0.08em; margin-bottom:8px"
          >
            事件類型（reason）
          </div>
          <div class="grid grid-cols-2" style="gap:6px">
            <div
              v-for="(d, k) in EVENT_DESC"
              :key="k"
              class="flex"
              style="gap:8px; align-items:flex-start; background:#12151b; border-radius:6px; padding:7px 10px"
            >
              <div
                style="width:6px; height:6px; border-radius:50%; flex-shrink:0; margin-top:4px"
                :style="{ background: d.color }"
              />
              <div>
                <div class="font-mono" style="font-size:11px" :style="{ color: d.color }">{{ k }}</div>
                <div style="font-size:10px; color:#505c6e; margin-top:2px">{{ d.label }}・{{ d.desc }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 決策紀錄表 -->
    <div
      style="background:#191d24; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04); overflow:hidden"
    >
      <div
        class="flex items-center justify-between flex-wrap"
        style="padding:10px 16px; border-bottom:1px solid #21262f; gap:12px"
      >
        <span class="font-mono shrink-0" style="font-size:11px; color:#505c6e">
          決策紀錄 · 點擊任一筆查看詳情
        </span>
        <DateFilterBar
          :mode="dateMode"
          :date-from="dateFrom"
          :date-to="dateTo"
          quick-bg="#f5c518"
          @change="handleDateChange"
        />
      </div>

      <DataTable
        :columns="columns"
        :rows="paginatedDecisions"
        :selected-id="selected?.id ?? null"
        @select="(r: Decision) => selected = r"
      >
        <template #cell-created_at="{ value }">
          <span style="white-space:nowrap">{{ fmtDT(value) }}</span>
        </template>
        <template #cell-classification="{ value }">
          <span
            class="font-mono"
            style="padding:2px 8px; border-radius:4px; font-size:10px"
            :style="{
              background: ((DECISION_DESC[value]?.color) || '#8a97a8') + '22',
              color:       (DECISION_DESC[value]?.color)  || '#8a97a8',
            }"
          >
            {{ value || '—' }}
          </span>
        </template>
        <template #cell-reason="{ value }">
          <span
            class="font-mono"
            style="padding:2px 8px; border-radius:4px; font-size:10px"
            :style="{
              background: ((EVENT_DESC[value]?.color) || '#8a97a8') + '22',
              color:       (EVENT_DESC[value]?.color)  || '#8a97a8',
            }"
          >
            {{ value || '—' }}
          </span>
        </template>
        <template #cell-latency_ms="{ value }">
          {{ value ? `${value}ms` : '—' }}
        </template>
        <template #cell-tokens_prompt="{ value }">
          {{ value ?? '—' }}
        </template>
        <template #cell-user_accepted="{ value }">
          <span v-if="value === 1" class="font-mono" style="color:#00e676; font-size:10px">● 採納</span>
          <span v-else-if="value === 0" class="font-mono" style="color:#ff5252; font-size:10px">● 未採納</span>
          <span v-else style="color:#505c6e; font-size:10px">—</span>
        </template>
      </DataTable>

      <div
        v-if="decisions.length === 0 && !loading"
        class="font-mono"
        style="padding:24px; text-align:center; font-size:12px; color:#505c6e"
      >
        此時間範圍無決策紀錄
      </div>

      <Pagination
        :total="decisions.length"
        :page-size="pageSize"
        :current="currentPage"
        active-color="#f5c518"
        @update:current="(v) => currentPage = v"
        @update:pageSize="(v) => pageSize = v"
      />
    </div>

    <!-- 決策詳情 -->
    <DetailPanel :open="!!selected" title="決策詳情" @close="selected = null">
      <div v-if="selected" class="flex flex-col" style="gap:14px">
        <!-- 決策類型 + 事件類型 -->
        <div class="flex" style="gap:8px">
          <div class="flex-1" style="background:#12151b; border-radius:8px; padding:9px 11px">
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:4px">決策類型</div>
            <span
              class="font-mono"
              style="padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600"
              :style="{
                background: (selDec?.color || '#8a97a8') + '22',
                color:       selDec?.color || '#8a97a8',
              }"
            >{{ selected.classification || '—' }}</span>
            <div style="font-size:11px; color:#edf0f4; margin-top:4px">{{ selDec?.label || '' }}</div>
            <div style="font-size:10px; color:#505c6e; margin-top:2px; line-height:1.5">{{ selDec?.desc || '' }}</div>
          </div>
          <div class="flex-1" style="background:#12151b; border-radius:8px; padding:9px 11px">
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:4px">事件類型</div>
            <span
              class="font-mono"
              style="padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600"
              :style="{
                background: (selEvt?.color || '#8a97a8') + '22',
                color:       selEvt?.color || '#8a97a8',
              }"
            >{{ selected.reason || '—' }}</span>
            <div style="font-size:11px; color:#edf0f4; margin-top:4px">{{ selEvt?.label || '' }}</div>
            <div style="font-size:10px; color:#505c6e; margin-top:2px; line-height:1.5">{{ selEvt?.desc || '' }}</div>
          </div>
        </div>

        <!-- 時間 + Latency + Tokens -->
        <div class="grid grid-cols-2" style="gap:8px">
          <div
            v-for="m in selMeta"
            :key="m.k"
            style="background:#12151b; border-radius:6px; padding:7px 9px"
          >
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:2px">{{ m.k }}</div>
            <div class="font-mono" style="font-size:12px; color:#edf0f4">{{ m.v }}</div>
          </div>
        </div>

        <!-- Session UUID -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:4px">
            Claude Code Session UUID
          </div>
          <div class="font-mono" style="font-size:11px; color:#8a97a8; word-break:break-all; margin-bottom:3px">
            {{ selected.session_id ?? '—' }}
          </div>
          <div style="font-size:10px; color:#505c6e; line-height:1.5">
            同一會話內多筆決策共用此 UUID。對話內容見下方「決策時的對話脈絡」。
          </div>
        </div>

        <!-- Prompt Hash -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:3px">
            Prompt Hash（SHA256 前 12 碼，不存明文）
          </div>
          <div class="font-mono" style="font-size:12px; color:#edf0f4">{{ selected.prompt_hash ?? '—' }}</div>
        </div>

        <!-- Qwen 建議 -->
        <div
          v-if="selected.local_output"
          style="background:#12151b; border-radius:8px; padding:9px 11px"
        >
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:6px">
            Qwen 建議（注入上下文的內容，前 500 字）
          </div>
          <div
            class="font-mono"
            style="font-size:11px; color:#8a97a8; white-space:pre-wrap; word-break:break-all; max-height:140px; overflow-y:auto; line-height:1.6"
          >
            {{ selected.local_output }}
          </div>
        </div>

        <!-- 對話脈絡 -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:8px">
            決策時的對話脈絡（來自 Layer 1，供判斷是否採納）
          </div>
          <div v-if="!selected.session_id" style="font-size:11px; color:#505c6e">此筆決策無 session_id</div>
          <div
            v-else-if="ctxLoading"
            class="font-mono"
            style="font-size:11px; color:#505c6e; padding:8px 0"
          >
            載入對話內容…
          </div>
          <div
            v-else-if="ctx?.error && (!ctx.messages || ctx.messages.length === 0)"
            class="font-mono"
            style="font-size:11px; color:#ff5252"
          >
            {{ ctx.error === 'session not found in Layer 1'
              ? '此 Session 不在 Layer 1 記錄中（可能早於 stop_hook 建置）'
              : `無法取得對話：${ctx.error}` }}
          </div>
          <div
            v-else-if="!ctx?.messages?.length"
            class="font-mono"
            style="font-size:11px; color:#505c6e"
          >
            此 Session 無可顯示的對話紀錄
          </div>
          <div v-else class="flex flex-col" style="gap:8px">
            <div
              v-for="(m, i) in ctx.messages"
              :key="i"
              style="border-radius:8px; padding:8px 10px"
              :style="{
                background: m.role === 'user' ? '#12151b' : '#1a2030',
                borderLeft: `3px solid ${m.role === 'user' ? '#40c4ff' : '#c084fc'}`,
              }"
            >
              <div
                class="font-mono"
                style="font-size:10px; margin-bottom:4px"
                :style="{ color: m.role === 'user' ? '#40c4ff' : '#c084fc' }"
              >
                {{ m.role === 'user' ? '👤 User' : '🤖 Assistant' }}{{ m.has_tool_use ? ' · 使用工具' : '' }}
              </div>
              <div style="font-size:11px; color:#8a97a8; white-space:pre-wrap; word-break:break-all; line-height:1.6">
                <template v-if="m.content">
                  {{ m.content.slice(0, 400) }}<span v-if="m.content.length > 400" style="color:#505c6e"> …（已截斷）</span>
                </template>
                <span v-else style="color:#505c6e">[tool call / 無文字內容]</span>
              </div>
            </div>
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-top:4px">
              ↑ 顯示決策時間點（{{ fmtDT(ctx.decision_at) }}）前的最近 8 筆有內容訊息
            </div>
          </div>
        </div>

        <!-- 採納操作 -->
        <div>
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:7px">
            根據以上對話判斷 Qwen 建議是否被採用
          </div>
          <div class="flex" style="gap:8px">
            <button
              @click="handleAcceptance(selected.id, true)"
              class="font-mono border-0 cursor-pointer"
              style="flex:1; padding:8px 0; border-radius:7px; font-size:12px; font-weight:600"
              :style="{
                background: selected.user_accepted === 1 ? '#00e676' : '#21262f',
                color:       selected.user_accepted === 1 ? '#12151b' : '#8a97a8',
              }"
            >✓ 採納</button>
            <button
              @click="handleAcceptance(selected.id, false)"
              class="font-mono border-0 cursor-pointer"
              style="flex:1; padding:8px 0; border-radius:7px; font-size:12px; font-weight:600"
              :style="{
                background: selected.user_accepted === 0 ? '#ff5252' : '#21262f',
                color:       selected.user_accepted === 0 ? '#fff'    : '#8a97a8',
              }"
            >✗ 未採納</button>
          </div>
        </div>
      </div>
    </DetailPanel>
  </div>
</template>

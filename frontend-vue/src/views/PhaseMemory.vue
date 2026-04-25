<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api/client'
import { buildDateQS, fmtDT } from '../api/dateFilter'
import type { Column } from '../components/shared/DataTable.vue'
import type { DateMode } from '../components/shared/DateFilterBar.vue'
import SectionHeader   from '../components/shared/SectionHeader.vue'
import StatCard        from '../components/shared/StatCard.vue'
import DataTable       from '../components/shared/DataTable.vue'
import DetailPanel     from '../components/shared/DetailPanel.vue'
import Btn             from '../components/shared/Btn.vue'
import DateFilterBar   from '../components/shared/DateFilterBar.vue'
import Pagination      from '../components/shared/Pagination.vue'
import MemoryBarChart  from '../components/MemoryBarChart.vue'

interface Session {
  id: number
  uuid: string | null
  started_at: string | null
  ended_at: string | null
  event_types: string | null
  exchange_count: number | null
  files_modified: number | null
  commits: number | null
  context_summary: string | null
}
interface Message {
  role: 'user' | 'assistant' | string
  content: string | null
  has_tool_use: boolean
}
interface Stats {
  total_sessions?: number
  week_total?: number
  avg_exchanges?: number
  avg_commits?: number
  trend?: Record<string, Record<string, number>>
}

const ET_DESC: Record<string, { color: string; label: string; desc: string }> = {
  git_ops:         { color:'#f5c518', label:'Git 操作',         desc:'commit / branch / merge / rebase' },
  terminal_ops:    { color:'#00e676', label:'終端機指令',       desc:'shell / 腳本 / 路徑 / 環境變數' },
  code_gen:        { color:'#40c4ff', label:'程式碼生成',       desc:'新增或修改程式碼、函式、模組' },
  debugging:       { color:'#ff5252', label:'除錯',             desc:'錯誤排查、測試修復、stack trace' },
  architecture:    { color:'#c084fc', label:'架構設計',         desc:'系統設計、技術選型、模組拆分' },
  knowledge_qa:    { color:'#00bfa5', label:'知識問答',         desc:'概念解釋、文件查詢、技術說明' },
  fine_tuning_ops: { color:'#ffab40', label:'Fine-tuning 操作', desc:'訓練 / 評分 / 資料集 / Adapter' },
}

const selected = ref<Session | null>(null)
const sessions = ref<Session[]>([])
const stats    = ref<Stats | null>(null)
const loading  = ref(true)
const error    = ref<string | null>(null)

// 日期篩選
const dateMode = ref<DateMode>('today')
const dateFrom = ref('')
const dateTo   = ref('')
// 分頁
const pageSize    = ref(10)
const currentPage = ref(1)
// Legend 折疊
const legendOpen = ref(false)

// 當 sessions 或 pageSize 變 → 重置到第一頁
watch([sessions, pageSize], () => { currentPage.value = 1 })

async function fetchData(mode: DateMode = dateMode.value, from = dateFrom.value, to = dateTo.value) {
  loading.value = true
  error.value = null
  const qs = buildDateQS(mode, from, to)
  try {
    const [sess, st] = await Promise.all([
      api.get<Session[]>(`/memory/sessions?limit=500${qs ? '&' + qs : ''}`),
      api.get<Stats>('/memory/stats'),
    ])
    sessions.value = sess
    stats.value = st
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(() => fetchData())

function handleDateChange(payload: { mode: DateMode; from: string; to: string }) {
  dateMode.value = payload.mode
  dateFrom.value = payload.from
  dateTo.value = payload.to
  fetchData(payload.mode, payload.from, payload.to)
}

const paginatedSessions = computed(() =>
  sessions.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value)
)

const columns: Column[] = [
  { key: 'ended_at',       label: '結束時間', mono: true },
  { key: 'uuid',           label: 'Session',  mono: true },
  { key: 'event_types',    label: '事件類型' },
  { key: 'exchange_count', label: '對話',    mono: true },
  { key: 'files_modified', label: '檔案',    mono: true },
  { key: 'commits',        label: 'Commits', mono: true },
]

function parseEventTypes(v: string | null): string[] {
  if (!v) return []
  try { return JSON.parse(v) } catch { return [] }
}

// Selected session messages
const selectedMsgs = ref<Message[] | null>(null)
const msgsLoading = ref(false)
watch(selected, async (s) => {
  if (!s) { selectedMsgs.value = null; return }
  msgsLoading.value = true
  try {
    selectedMsgs.value = await api.get<Message[]>(`/memory/sessions/${s.id}/messages?limit=10`)
  } catch {
    selectedMsgs.value = []
  } finally {
    msgsLoading.value = false
  }
})

const selectedEventTypes = computed(() => selected.value ? parseEventTypes(selected.value.event_types) : [])
</script>

<template>
  <div class="flex-1 flex flex-col" style="min-width:0">
    <SectionHeader
      title="日常記憶層"
      sub="Layer 1 · Stop Hook → SQLite → FTS5 + BGE-M3 向量搜尋"
      accent="#40c4ff"
    >
      <template #actions>
        <Btn variant="ghost" @click="fetchData()">刷新</Btn>
      </template>
    </SectionHeader>

    <div v-if="error" class="font-mono" style="color:#ff5252; font-size:12px; margin-bottom:8px">
      API 錯誤：{{ error }}
    </div>
    <div v-if="loading" class="font-mono" style="color:#505c6e; font-size:12px; margin-bottom:8px">
      載入中…
    </div>

    <!-- StatCards -->
    <div class="grid grid-cols-4" style="gap:10px; margin-bottom:18px">
      <StatCard label="總 Sessions"    :value="stats?.total_sessions ?? '—'" sub="全部歷史" />
      <StatCard label="近7天 Sessions" :value="stats?.week_total ?? '—'" sub="7 天內" color="#40c4ff" />
      <StatCard label="平均對話回合"   :value="stats?.avg_exchanges ?? '—'" sub="每 session" color="#00e676" />
      <StatCard label="平均 Commits"   :value="stats?.avg_commits ?? '—'" sub="每 session" color="#f5c518" />
    </div>

    <!-- 7 日趨勢 -->
    <div
      style="background:#191d24; border-radius:12px; padding:18px 20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div
        class="font-mono uppercase"
        style="font-size:11px; color:#505c6e; letter-spacing:0.06em; margin-bottom:12px"
      >
        對話數量趨勢 · 7天
      </div>
      <MemoryBarChart :trend="stats?.trend ?? null" />
      <div class="flex flex-wrap" style="gap:12px; margin-top:10px">
        <div
          v-for="[name, d] in Object.entries(ET_DESC)"
          :key="name"
          class="flex items-center font-mono"
          style="gap:4px; font-size:10px; color:#8a97a8"
        >
          <div class="rounded-sm" style="width:8px; height:8px" :style="{ background: d.color }" />
          {{ name }}
        </div>
      </div>
    </div>

    <!-- Event Legend（折疊） -->
    <div
      style="margin-bottom:14px; border-radius:10px; background:#191d24; border:1px solid #21262f; overflow:hidden"
    >
      <button
        @click="legendOpen = !legendOpen"
        class="w-full flex justify-between items-center bg-transparent border-0 cursor-pointer font-mono text-left"
        style="padding:9px 14px; font-size:11px; color:#505c6e"
      >
        <span>事件類型說明</span>
        <span style="font-size:10px">{{ legendOpen ? '▲' : '▼' }}</span>
      </button>
      <div v-if="legendOpen" style="padding:0 14px 14px">
        <div class="grid grid-cols-2" style="gap:6px">
          <div
            v-for="[k, d] in Object.entries(ET_DESC)"
            :key="k"
            class="flex items-start"
            style="background:#12151b; border-radius:6px; padding:7px 10px; gap:8px"
          >
            <div
              class="rounded-full shrink-0"
              style="width:6px; height:6px; margin-top:4px"
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

    <!-- Session 紀錄表 -->
    <div
      style="background:#191d24; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div
        class="flex items-center flex-wrap"
        style="padding:10px 16px; border-bottom:1px solid #21262f; gap:12px; justify-content:space-between"
      >
        <span class="font-mono shrink-0" style="font-size:11px; color:#505c6e">
          Session 紀錄 · 點擊任一筆查看詳情
        </span>
        <DateFilterBar
          :mode="dateMode"
          :date-from="dateFrom"
          :date-to="dateTo"
          quick-bg="#40c4ff"
          @update:mode="dateMode = $event"
          @update:date-from="dateFrom = $event"
          @update:date-to="dateTo = $event"
          @change="handleDateChange"
        />
      </div>
      <DataTable
        :columns="columns"
        :rows="paginatedSessions"
        :selected-id="selected?.id ?? null"
        key-field="id"
        @select="(r: Session) => selected = r"
      >
        <template #cell-ended_at="{ value }">
          <span style="white-space:nowrap">{{ fmtDT(value) }}</span>
        </template>
        <template #cell-uuid="{ value }">
          <span style="color:#8a97a8">{{ value ? value.slice(0, 8) : '—' }}</span>
        </template>
        <template #cell-event_types="{ value }">
          <div v-if="parseEventTypes(value).length > 0" class="flex flex-wrap" style="gap:4px">
            <span
              v-for="et in parseEventTypes(value).slice(0, 3)"
              :key="et"
              class="font-mono"
              style="padding:1px 6px; border-radius:4px; font-size:10px"
              :style="{
                background: (ET_DESC[et]?.color ?? '#8a97a8') + '22',
                color:       ET_DESC[et]?.color ?? '#8a97a8',
              }"
            >
              {{ et }}
            </span>
            <span
              v-if="parseEventTypes(value).length > 3"
              style="color:#505c6e; font-size:10px"
            >
              +{{ parseEventTypes(value).length - 3 }}
            </span>
          </div>
          <span v-else style="color:#505c6e">—</span>
        </template>
        <template #cell-exchange_count="{ value }">
          <span style="color:#edf0f4">{{ value ?? 0 }}</span>
        </template>
        <template #cell-files_modified="{ value }">
          <span style="color:#40c4ff">{{ value ?? 0 }}</span>
        </template>
        <template #cell-commits="{ value }">
          <span style="color:#f5c518">{{ value ?? 0 }}</span>
        </template>
      </DataTable>
      <div
        v-if="sessions.length === 0 && !loading"
        class="font-mono text-center"
        style="padding:24px; font-size:12px; color:#505c6e"
      >
        此時間範圍無 Session 紀錄
      </div>
      <Pagination
        :total="sessions.length"
        :page-size="pageSize"
        :current="currentPage"
        active-color="#40c4ff"
        @update:current="currentPage = $event"
        @update:page-size="pageSize = $event"
      />
    </div>

    <!-- Detail Panel -->
    <DetailPanel :open="!!selected" title="Session 詳情" @close="selected = null">
      <div v-if="selected" class="flex flex-col" style="gap:14px">
        <!-- 事件類型 -->
        <div v-if="selectedEventTypes.length > 0">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:6px">事件類型</div>
          <div class="flex flex-wrap" style="gap:6px">
            <span
              v-for="et in selectedEventTypes"
              :key="et"
              class="font-mono"
              style="padding:2px 10px; border-radius:4px; font-size:11px"
              :style="{
                background: (ET_DESC[et]?.color ?? '#8a97a8') + '22',
                color:       ET_DESC[et]?.color ?? '#8a97a8',
              }"
            >
              {{ et }}
            </span>
          </div>
        </div>

        <!-- 2×2 時間 / 統計 -->
        <div class="grid grid-cols-2" style="gap:8px">
          <div
            v-for="item in [
              { k:'開始時間', v: fmtDT(selected.started_at) },
              { k:'結束時間', v: fmtDT(selected.ended_at) },
              { k:'對話回合', v: `${selected.exchange_count ?? 0} 回合` },
              { k:'修改檔案', v: `${selected.files_modified ?? 0} 個` },
            ]"
            :key="item.k"
            style="background:#12151b; border-radius:6px; padding:7px 9px"
          >
            <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:2px">{{ item.k }}</div>
            <div class="font-mono" style="font-size:12px; color:#edf0f4">{{ item.v }}</div>
          </div>
        </div>

        <!-- Commits -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:3px">Commits</div>
          <div
            class="font-mono font-bold"
            style="font-size:18px; color:#f5c518"
          >
            {{ selected.commits ?? 0 }}
          </div>
        </div>

        <!-- Session UUID -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:4px">
            Claude Code Session UUID
          </div>
          <div
            class="font-mono"
            style="font-size:11px; color:#8a97a8; word-break:break-all; margin-bottom:3px"
          >
            {{ selected.uuid ?? '—' }}
          </div>
        </div>

        <!-- context_summary -->
        <div v-if="selected.context_summary" style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:6px">
            Context 摘要（壓縮後）
          </div>
          <div
            style="font-size:11px; color:#8a97a8; white-space:pre-wrap; word-break:break-all; max-height:120px; overflow-y:auto; line-height:1.6"
          >
            {{ selected.context_summary }}
          </div>
        </div>

        <!-- 對話訊息 -->
        <div style="background:#12151b; border-radius:8px; padding:9px 11px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:8px">
            對話訊息（最近 10 筆）
          </div>
          <div v-if="msgsLoading" class="font-mono" style="font-size:11px; color:#505c6e">
            載入對話內容…
          </div>
          <div
            v-else-if="!selectedMsgs || selectedMsgs.length === 0"
            class="font-mono"
            style="font-size:11px; color:#505c6e"
          >
            此 Session 無可顯示的訊息
          </div>
          <div v-else class="flex flex-col" style="gap:8px">
            <div
              v-for="(m, i) in selectedMsgs"
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
                {{ m.role === 'user' ? '👤 User' : '🤖 Assistant' }}
                {{ m.has_tool_use ? ' · 使用工具' : '' }}
              </div>
              <div
                style="font-size:11px; color:#8a97a8; white-space:pre-wrap; word-break:break-all; line-height:1.6"
              >
                {{ (m.content || '').slice(0, 400) }}<span
                  v-if="m.content && m.content.length > 400"
                  style="color:#505c6e"
                > …（已截斷）</span>
              </div>
            </div>
            <div class="font-mono" style="font-size:10px; color:#505c6e">
              ↑ 顯示最近 10 筆有內容訊息
            </div>
          </div>
        </div>
      </div>
    </DetailPanel>
  </div>
</template>

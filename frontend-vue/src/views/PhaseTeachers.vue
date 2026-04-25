<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'
import type { Column } from '../components/shared/DataTable.vue'
import SectionHeader   from '../components/shared/SectionHeader.vue'
import StatCard        from '../components/shared/StatCard.vue'
import Badge           from '../components/shared/Badge.vue'
import StatusDot       from '../components/shared/StatusDot.vue'
import QuotaBar        from '../components/shared/QuotaBar.vue'
import DataTable       from '../components/shared/DataTable.vue'
import DetailPanel     from '../components/shared/DetailPanel.vue'
import Btn             from '../components/shared/Btn.vue'

interface Teacher {
  id: number
  name: string
  model_id: string
  priority: number
  is_active: boolean
  is_daily_limit_reached: boolean
  requests_today: number
  daily_request_limit: number
  daily_token_limit: number | null
  input_tokens_today: number
  output_tokens_today: number
  quota_reset_period: string
  quota_exhausted_at: string | null
}
interface Sample {
  id: number
  instruction: string | null
  event_type: string | null
  score: number | null
  score_reason: string | null
  status: string
}

const teachers = ref<Teacher[]>([])
const votes    = ref<Sample[]>([])
const selected = ref<Sample | null>(null)
const tab      = ref<'teachers' | 'votes'>('teachers')
const loading  = ref(true)
const error    = ref<string | null>(null)

async function fetchAll() {
  loading.value = true
  error.value = null
  try {
    const [t, v] = await Promise.all([
      api.get<Teacher[]>('/teachers'),
      api.get<Sample[]>('/samples?status=pending&limit=50'),
    ])
    teachers.value = t
    votes.value = v
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(fetchAll)

async function handleToggle(id: number) {
  const t = teachers.value.find(x => x.id === id)
  if (!t) return
  await api.patch(`/teachers/${id}`, { is_active: !t.is_active })
  const fresh = await api.get<Teacher[]>('/teachers')
  teachers.value = fresh
}
async function handleApprove(id: number) {
  await api.post(`/samples/${id}/approve`)
  votes.value = await api.get<Sample[]>('/samples?status=pending&limit=50')
  selected.value = null
}
async function handleReject(id: number) {
  await api.post(`/samples/${id}/reject`)
  votes.value = await api.get<Sample[]>('/samples?status=pending&limit=50')
  selected.value = null
}

const activeCount    = computed(() => teachers.value.filter(t => t.is_active).length)
const exhaustedCount = computed(() => teachers.value.filter(t => t.is_daily_limit_reached).length)
const reviewCount    = computed(() => votes.value.filter(v => v.status === 'needs_review').length)

const voteColumns: Column[] = [
  { key: 'instruction', label: '問題' },
  { key: 'event_type',  label: '事件' },
  { key: 'score',       label: '分數', mono: true },
  { key: 'status',      label: '狀態' },
]

function scoreColor(s: number | null | undefined) {
  if (s == null) return '#505c6e'
  return s >= 8 ? '#00e676' : s >= 6 ? '#ffab40' : '#ff5252'
}
</script>

<template>
  <div class="flex-1 flex flex-col" style="min-width:0">
    <SectionHeader
      title="師父管理"
      sub="Layer 2 · 精神時光屋 — Teacher 配額監控、投票評分、人工審核"
      accent="#c084fc"
    >
      <template #actions>
        <Btn variant="ghost" @click="fetchAll">刷新配額</Btn>
      </template>
    </SectionHeader>

    <div v-if="error" class="font-mono" style="color:#ff5252; font-size:12px; margin-bottom:8px">
      API 錯誤：{{ error }}
    </div>
    <div v-if="loading" class="font-mono" style="color:#505c6e; font-size:12px; margin-bottom:8px">
      載入中…
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-4" style="gap:10px; margin-bottom:20px">
      <StatCard label="啟用師父" :value="activeCount" :sub="`共 ${teachers.length} 位`" color="#00e676" />
      <StatCard label="配額耗盡" :value="exhaustedCount" sub="今日" :color="exhaustedCount > 0 ? '#ff5252' : '#00e676'" />
      <StatCard label="待審核"   :value="reviewCount" sub="needs_review" :color="reviewCount > 0 ? '#ffab40' : '#00e676'" />
      <StatCard label="Pending 樣本" :value="votes.length" sub="training samples" color="#c084fc" />
    </div>

    <!-- Tabs -->
    <div class="flex" style="margin-bottom:16px; border-bottom:1px solid #21262f">
      <button
        v-for="[k, l] in [['teachers','師父列表'],['votes','投票紀錄']] as const"
        :key="k"
        @click="tab = k"
        class="bg-transparent border-0 cursor-pointer font-body transition-colors"
        style="padding:8px 18px; font-size:13px; letter-spacing:-0.01em"
        :style="{
          color:         tab === k ? '#edf0f4' : '#505c6e',
          borderBottom:  tab === k ? '2px solid #c084fc' : '2px solid transparent',
        }"
      >
        {{ l }}
      </button>
    </div>

    <!-- Teachers grid -->
    <div v-if="tab === 'teachers'" class="grid grid-cols-2" style="gap:12px">
      <div
        v-for="t in teachers"
        :key="t.id"
        style="background:#191d24; border-radius:12px; padding:16px"
        :style="{
          boxShadow: `0 2px 8px rgba(0,0,0,0.5), 0 0 0 1px ${t.is_daily_limit_reached ? 'rgba(255,82,82,0.2)' : 'rgba(255,255,255,0.04)'}`,
        }"
      >
        <div class="flex items-center justify-between" style="margin-bottom:10px">
          <div class="flex items-center" style="gap:8px">
            <StatusDot :state="!t.is_active ? 'inactive' : t.is_daily_limit_reached ? 'error' : 'active'" />
            <span class="font-display font-semibold" style="font-size:13px; color:#edf0f4">{{ t.name }}</span>
            <Badge type="neutral">p{{ t.priority }}</Badge>
            <Badge v-if="t.is_daily_limit_reached" type="rejected">耗盡</Badge>
          </div>
          <Btn variant="ghost" @click="handleToggle(t.id)">
            {{ t.is_active ? '停用' : '啟用' }}
          </Btn>
        </div>
        <div class="font-mono" style="font-size:11px; color:#505c6e; margin-bottom:12px">{{ t.model_id }}</div>

        <QuotaBar
          :used="t.requests_today"
          :limit="t.daily_request_limit"
          label="req 今日"
          :sublabel="(t.input_tokens_today + t.output_tokens_today) > 0
            ? `tokens: ${(t.input_tokens_today + t.output_tokens_today).toLocaleString()} · 重置: ${t.quota_reset_period}`
            : `重置: ${t.quota_reset_period}`"
        />
        <div v-if="t.daily_token_limit" style="margin-top:10px">
          <QuotaBar
            :used="t.input_tokens_today + t.output_tokens_today"
            :limit="t.daily_token_limit"
            label="tokens 今日"
          />
        </div>
        <div
          v-if="t.quota_exhausted_at"
          class="font-mono"
          style="margin-top:8px; font-size:11px; color:#ff5252"
        >
          耗盡：{{ t.quota_exhausted_at }}
        </div>
      </div>
    </div>

    <!-- Votes table -->
    <div
      v-else
      style="background:#191d24; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div
        class="font-mono"
        style="padding:10px 16px; border-bottom:1px solid #21262f; font-size:11px; color:#505c6e"
      >
        今日問題投票紀錄 · 點擊查看詳情
      </div>
      <DataTable
        :columns="voteColumns"
        :rows="votes"
        :selected-id="selected?.id ?? null"
        @select="(r: Sample) => selected = r"
      >
        <template #cell-instruction="{ value }">
          <span style="color:#edf0f4; font-size:12px">
            {{ value && value.length > 38 ? value.slice(0, 38) + '…' : value || '—' }}
          </span>
        </template>
        <template #cell-event_type="{ value }">
          <Badge :type="value ?? 'neutral'">{{ value || '—' }}</Badge>
        </template>
        <template #cell-score="{ value }">
          <span v-if="value != null" :style="{ color: scoreColor(value), fontWeight: 600 }">
            {{ value.toFixed(1) }}
          </span>
          <span v-else>—</span>
        </template>
        <template #cell-status="{ value }">
          <Badge :type="value">{{ value }}</Badge>
        </template>
      </DataTable>
    </div>

    <!-- Detail panel -->
    <DetailPanel :open="!!selected" title="投票詳情" @close="selected = null">
      <div v-if="selected" class="flex flex-col" style="gap:14px">
        <div class="flex flex-wrap" style="gap:6px">
          <Badge :type="selected.status">{{ selected.status }}</Badge>
          <Badge :type="selected.event_type ?? 'neutral'">{{ selected.event_type || '—' }}</Badge>
          <Badge v-if="selected.status === 'needs_review'" type="warning">需人工審核</Badge>
        </div>
        <div
          style="font-size:13px; color:#edf0f4; background:#21262f; padding:10px 12px; border-radius:8px; line-height:1.6"
        >
          {{ selected.instruction || '—' }}
        </div>
        <div
          class="flex items-center justify-between"
          style="padding:10px 12px; background:#033848; border-radius:8px; border:1px solid #06c8e840"
        >
          <span style="font-size:13px; color:#8a97a8; font-weight:600">評分</span>
          <span
            class="font-mono font-bold"
            style="font-size:18px"
            :style="{ color: scoreColor(selected.score) }"
          >
            {{ selected.score != null ? selected.score.toFixed(1) : '—' }}
          </span>
        </div>
        <div
          v-if="selected.score_reason"
          style="font-size:12px; color:#8a97a8; background:#21262f; padding:8px 12px; border-radius:8px; line-height:1.5"
        >
          {{ selected.score_reason }}
        </div>
        <div class="flex" style="gap:8px">
          <Btn
            variant="ghost"
            style="flex:1; justify-content:center; color:#00e676; border:1px solid #00e67640"
            @click="handleApprove(selected.id)"
          >
            手動 Approve
          </Btn>
          <Btn variant="danger" style="flex:1; justify-content:center" @click="handleReject(selected.id)">
            手動 Reject
          </Btn>
        </div>
      </div>
    </DetailPanel>
  </div>
</template>

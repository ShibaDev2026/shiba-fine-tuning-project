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
import Modal           from '../components/shared/Modal.vue'
import ConfirmDialog   from '../components/shared/ConfirmDialog.vue'
import FormField       from '../components/shared/FormField.vue'
import { useToastStore } from '../stores/toast'

const toast = useToastStore()

interface Teacher {
  id: number
  name: string
  model_id: string
  api_base: string
  vendor: string
  priority: number
  is_active: boolean
  is_daily_limit_reached: boolean
  today_requests: number
  daily_request_limit: number
  daily_token_limit: number | null
  input_tokens_today: number
  output_tokens_today: number
  quota_reset_period: string
  quota_exhausted_at: string | null
  quota_exhausted_type: string | null
  has_api_key: boolean
  created_at: string | null
  quota_remaining: number | null
}

interface Sample {
  id: number
  instruction: string | null
  event_type: string | null
  score: number | null
  score_reason: string | null
  status: string
}

interface TestResult {
  response: string | null
  latency_ms: number
  error: string | null
}

// ── 資料 ─────────────────────────────────────────────────
const teachers = ref<Teacher[]>([])
const votes    = ref<Sample[]>([])
const loading  = ref(true)
const error    = ref<string | null>(null)

// ── 選取狀態（師父 / 投票各自獨立）─────────────────────
const selectedTeacher = ref<Teacher | null>(null)
const selectedVote    = ref<Sample | null>(null)
const tab             = ref<'teachers' | 'votes'>('teachers')

// ── 測試連線 ─────────────────────────────────────────────
const testResult = ref<TestResult | null>(null)
const testing    = ref(false)

// ── ConfirmDialog（停用/啟用）────────────────────────────
const confirmToggle   = ref(false)
const pendingToggleId = ref<number | null>(null)

// ── TeacherFormModal ─────────────────────────────────────
const showForm    = ref(false)
const formMode    = ref<'create' | 'edit'>('create')
const formLoading = ref(false)
const formErrors  = ref<Record<string, string>>({})
const formData    = ref({
  name: '',
  model_id: '',
  api_base: '',
  vendor: 'unknown',
  priority: 0,
  daily_request_limit: 250,
  daily_token_limit: '' as number | '',
  quota_reset_period: 'daily',
  is_active: true,
})

// ── 資料載入 ─────────────────────────────────────────────
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
    // 更新已開啟的師父詳情
    if (selectedTeacher.value) {
      selectedTeacher.value = t.find(x => x.id === selectedTeacher.value!.id) ?? null
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(fetchAll)

// ── 操作：選取 ────────────────────────────────────────────
function openTeacher(t: Teacher) {
  selectedTeacher.value = t
  selectedVote.value = null
  testResult.value = null
}

function openVote(s: Sample) {
  selectedVote.value = s
  selectedTeacher.value = null
}

// ── 操作：停用/啟用 ───────────────────────────────────────
function requestToggle(id: number) {
  pendingToggleId.value = id
  confirmToggle.value = true
}

async function confirmDoToggle() {
  confirmToggle.value = false
  const id = pendingToggleId.value
  pendingToggleId.value = null
  if (!id) return
  const t = teachers.value.find(x => x.id === id)
  if (!t) return
  try {
    await api.patch(`/teachers/${id}`, { is_active: !t.is_active })
    toast.push(`${t.name} 已${t.is_active ? '停用' : '啟用'}`, 'success')
    await fetchAll()
  } catch (e) {
    toast.push(`操作失敗：${(e as Error).message}`, 'error')
  }
}

// ── 操作：測試連線 ────────────────────────────────────────
async function handleTest(id: number) {
  testing.value = true
  testResult.value = null
  try {
    const r = await api.post<TestResult>(`/teachers/${id}/test`, {})
    testResult.value = r
  } catch (e) {
    testResult.value = { response: null, latency_ms: 0, error: (e as Error).message }
  } finally {
    testing.value = false
  }
}

// ── 操作：投票 ────────────────────────────────────────────
async function handleApprove(id: number) {
  await api.post(`/samples/${id}/approve`)
  votes.value = await api.get<Sample[]>('/samples?status=pending&limit=50')
  selectedVote.value = null
}
async function handleReject(id: number) {
  await api.post(`/samples/${id}/reject`)
  votes.value = await api.get<Sample[]>('/samples?status=pending&limit=50')
  selectedVote.value = null
}

// ── 操作：表單 ────────────────────────────────────────────
function openCreate() {
  formMode.value = 'create'
  formErrors.value = {}
  formData.value = { name: '', model_id: '', api_base: '', vendor: 'unknown', priority: 0, daily_request_limit: 250, daily_token_limit: '', quota_reset_period: 'daily', is_active: true }
  showForm.value = true
}

function openEdit(t: Teacher) {
  formMode.value = 'edit'
  formErrors.value = {}
  formData.value = {
    name: t.name,
    model_id: t.model_id,
    api_base: t.api_base,
    vendor: t.vendor,
    priority: t.priority,
    daily_request_limit: t.daily_request_limit,
    daily_token_limit: t.daily_token_limit ?? '',
    quota_reset_period: t.quota_reset_period,
    is_active: t.is_active,
  }
  showForm.value = true
}

function validateForm(): boolean {
  const errs: Record<string, string> = {}
  if (!formData.value.name.trim()) errs.name = '必填'
  if (!formData.value.model_id.trim()) errs.model_id = '必填'
  if (!formData.value.api_base.trim()) errs.api_base = '必填'
  else if (!/^https?:\/\/.+/.test(formData.value.api_base)) errs.api_base = '請輸入合法 URL（http:// 或 https://）'
  if (formData.value.daily_request_limit < 1) errs.daily_request_limit = '至少 1'
  formErrors.value = errs
  return Object.keys(errs).length === 0
}

async function submitForm() {
  if (!validateForm()) return
  formLoading.value = true
  try {
    const payload = {
      ...formData.value,
      daily_token_limit: formData.value.daily_token_limit === '' ? null : Number(formData.value.daily_token_limit),
    }
    if (formMode.value === 'create') {
      await api.post('/teachers', payload)
      toast.push(`師父 ${payload.name} 建立成功！請執行 setup_teachers.py --setup 設定 API Key`, 'success')
      showForm.value = false
      await fetchAll()
    } else {
      const t = teachers.value.find(x => x.name === formData.value.name)
      if (!t) throw new Error('找不到師父 ID')
      const { name: _n, ...updatePayload } = payload
      await api.put(`/teachers/${t.id}`, updatePayload)
      toast.push(`師父 ${payload.name} 更新成功`, 'success')
      showForm.value = false
      await fetchAll()
      // 保持詳情面板開啟
      const fresh = teachers.value.find(x => x.id === t.id)
      if (fresh) selectedTeacher.value = fresh
    }
  } catch (e) {
    toast.push(`失敗：${(e as Error).message}`, 'error')
  } finally {
    formLoading.value = false
  }
}

// ── 計算屬性 ─────────────────────────────────────────────
const activeCount    = computed(() => teachers.value.filter(t => t.is_active).length)
const exhaustedCount = computed(() => teachers.value.filter(t => t.is_daily_limit_reached).length)
const reviewCount    = computed(() => votes.value.filter(v => v.status === 'needs_review').length)

const voteColumns: Column[] = [
  { key: 'instruction', label: '問題' },
  { key: 'event_type',  label: '事件' },
  { key: 'score',       label: '分數', mono: true },
  { key: 'status',      label: '狀態' },
]

const VENDOR_COLOR: Record<string, string> = {
  google: '#4285f4', xai: '#c0c0c0', openai: '#00a67e',
  mistral: '#fa8231', anthropic: '#c084fc', local: '#40c4ff',
}

const pendingTeacher = computed(() =>
  teachers.value.find(x => x.id === pendingToggleId.value)
)

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
        <Btn variant="primary" style="margin-left:6px" @click="openCreate">+ 新增師父</Btn>
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
          color:        tab === k ? '#edf0f4' : '#505c6e',
          borderBottom: tab === k ? '2px solid #c084fc' : '2px solid transparent',
        }"
      >
        {{ l }}
      </button>
    </div>

    <!-- ── Teachers Grid ── -->
    <div v-if="tab === 'teachers'" class="grid grid-cols-2" style="gap:12px">
      <div
        v-for="t in teachers"
        :key="t.id"
        style="background:#191d24; border-radius:12px; padding:16px; cursor:pointer; transition:box-shadow 120ms, opacity 180ms, filter 180ms"
        :style="{
          opacity: t.is_active ? 1 : 0.45,
          filter:  t.is_active ? 'none' : 'grayscale(0.6)',
          boxShadow: selectedTeacher?.id === t.id
            ? '0 2px 8px rgba(0,0,0,0.5), 0 0 0 2px #c084fc60'
            : `0 2px 8px rgba(0,0,0,0.5), 0 0 0 1px ${t.is_daily_limit_reached ? 'rgba(255,82,82,0.2)' : 'rgba(255,255,255,0.04)'}`,
        }"
        @click="openTeacher(t)"
      >
        <div class="flex items-center justify-between" style="margin-bottom:10px">
          <div class="flex items-center" style="gap:8px; flex-wrap:wrap">
            <StatusDot :state="!t.is_active ? 'inactive' : t.is_daily_limit_reached ? 'error' : 'active'" />
            <span class="font-display font-semibold" style="font-size:13px; color:#edf0f4">{{ t.name }}</span>
            <Badge type="neutral">p{{ t.priority }}</Badge>
            <Badge v-if="!t.is_active" type="rejected">停用中</Badge>
            <Badge v-else-if="t.is_daily_limit_reached" type="rejected">耗盡</Badge>
          </div>
          <Btn variant="ghost" style="flex-shrink:0" @click.stop="requestToggle(t.id)">
            {{ t.is_active ? '停用' : '啟用' }}
          </Btn>
        </div>
        <div class="font-mono" style="font-size:11px; color:#505c6e; margin-bottom:12px">{{ t.model_id }}</div>

        <QuotaBar
          :used="t.today_requests"
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
        <div v-if="t.quota_exhausted_at" class="font-mono" style="margin-top:8px; font-size:11px; color:#ff5252">
          耗盡：{{ t.quota_exhausted_at }}
        </div>
      </div>
    </div>

    <!-- ── Votes Table ── -->
    <div
      v-else
      style="background:#191d24; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div class="font-mono" style="padding:10px 16px; border-bottom:1px solid #21262f; font-size:11px; color:#505c6e">
        今日問題投票紀錄 · 點擊查看詳情
      </div>
      <DataTable
        :columns="voteColumns"
        :rows="votes"
        :selected-id="selectedVote?.id ?? null"
        @select="(r: Sample) => openVote(r)"
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
          <span v-if="value != null" :style="{ color: scoreColor(value), fontWeight: 600 }">{{ value.toFixed(1) }}</span>
          <span v-else>—</span>
        </template>
        <template #cell-status="{ value }">
          <Badge :type="value">{{ value }}</Badge>
        </template>
      </DataTable>
    </div>

    <!-- ── Detail Panel：師父詳情 ── -->
    <DetailPanel :open="!!selectedTeacher" title="師父詳情" @close="selectedTeacher = null; testResult = null">
      <div v-if="selectedTeacher" class="flex flex-col" style="gap:16px">

        <!-- 標題 -->
        <div class="flex items-center" style="gap:8px; flex-wrap:wrap">
          <StatusDot :state="!selectedTeacher.is_active ? 'inactive' : selectedTeacher.is_daily_limit_reached ? 'error' : 'active'" />
          <span class="font-display font-semibold" style="font-size:15px; color:#edf0f4">{{ selectedTeacher.name }}</span>
          <span
            class="font-mono"
            style="font-size:10px; padding:2px 8px; border-radius:4px"
            :style="{
              background: (VENDOR_COLOR[selectedTeacher.vendor] ?? '#8a97a8') + '22',
              color: VENDOR_COLOR[selectedTeacher.vendor] ?? '#8a97a8',
              border: '1px solid ' + (VENDOR_COLOR[selectedTeacher.vendor] ?? '#8a97a8') + '50',
            }"
          >{{ selectedTeacher.vendor }}</span>
          <Badge v-if="!selectedTeacher.is_active" type="rejected">停用中</Badge>
        </div>

        <!-- 基本資訊 -->
        <div style="background:#21262f; border-radius:8px; padding:10px 12px; display:flex; flex-direction:column; gap:6px">
          <div class="font-mono" style="font-size:11px; color:#edf0f4">{{ selectedTeacher.model_id }}</div>
          <div class="font-mono" style="font-size:10px; color:#8a97a8; word-break:break-all">{{ selectedTeacher.api_base }}</div>
          <div class="flex" style="gap:16px; margin-top:2px">
            <span class="font-mono" style="font-size:10px; color:#505c6e">priority <span style="color:#8a97a8">{{ selectedTeacher.priority }}</span></span>
            <span class="font-mono" style="font-size:10px; color:#505c6e">重置 <span style="color:#8a97a8">{{ selectedTeacher.quota_reset_period }}</span></span>
          </div>
          <div v-if="selectedTeacher.created_at" class="font-mono" style="font-size:10px; color:#505c6e">
            建立 {{ selectedTeacher.created_at }}
          </div>
        </div>

        <!-- API Key 狀態（密碼 plan 升級後替換此區塊） -->
        <div style="background:#21262f; border-radius:8px; padding:10px 12px">
          <div class="font-mono" style="font-size:10px; color:#505c6e; margin-bottom:6px">API Key</div>
          <Badge v-if="selectedTeacher.has_api_key" type="approved">已設定 (Keychain)</Badge>
          <div v-else class="flex flex-col" style="gap:4px">
            <Badge type="neutral" style="color:#ffab40; border-color:#ffab4040">未設定</Badge>
            <span class="font-mono" style="font-size:10px; color:#505c6e">請執行 setup_teachers.py --setup</span>
          </div>
        </div>

        <!-- QuotaBars -->
        <div class="flex flex-col" style="gap:10px">
          <QuotaBar
            :used="selectedTeacher.today_requests"
            :limit="selectedTeacher.daily_request_limit"
            label="req 今日"
            :sublabel="selectedTeacher.quota_remaining != null ? `剩餘 ${selectedTeacher.quota_remaining} 次` : ''"
          />
          <div v-if="selectedTeacher.daily_token_limit">
            <QuotaBar
              :used="selectedTeacher.input_tokens_today + selectedTeacher.output_tokens_today"
              :limit="selectedTeacher.daily_token_limit"
              label="tokens 今日"
            />
          </div>
          <div class="flex" style="gap:16px">
            <span class="font-mono" style="font-size:10px; color:#505c6e">in <span style="color:#8a97a8">{{ selectedTeacher.input_tokens_today.toLocaleString() }}</span></span>
            <span class="font-mono" style="font-size:10px; color:#505c6e">out <span style="color:#8a97a8">{{ selectedTeacher.output_tokens_today.toLocaleString() }}</span></span>
          </div>
          <div v-if="selectedTeacher.quota_exhausted_at" class="font-mono" style="font-size:10px; color:#ff5252">
            配額耗盡 {{ selectedTeacher.quota_exhausted_at }}
            <span v-if="selectedTeacher.quota_exhausted_type">({{ selectedTeacher.quota_exhausted_type }})</span>
          </div>
        </div>

        <!-- 測試連線結果 -->
        <div v-if="testResult" style="background:#21262f; border-radius:8px; padding:10px 12px">
          <div v-if="testResult.error" class="font-mono" style="color:#ff5252; font-size:11px">{{ testResult.error }}</div>
          <template v-else>
            <div class="font-mono" style="font-size:10px; color:#00e676; margin-bottom:6px">latency {{ testResult.latency_ms }}ms</div>
            <div style="font-size:12px; color:#edf0f4; line-height:1.6; white-space:pre-wrap">{{ testResult.response }}</div>
          </template>
        </div>

        <!-- 動作列 -->
        <div class="flex" style="gap:8px; flex-wrap:wrap">
          <Btn variant="cyan" :loading="testing" @click="handleTest(selectedTeacher.id)">測試連線</Btn>
          <Btn variant="ghost" @click="openEdit(selectedTeacher)">編輯</Btn>
          <Btn :variant="selectedTeacher.is_active ? 'danger' : 'ghost'" @click="requestToggle(selectedTeacher.id)">
            {{ selectedTeacher.is_active ? '停用' : '啟用' }}
          </Btn>
        </div>
      </div>
    </DetailPanel>

    <!-- ── Detail Panel：投票詳情 ── -->
    <DetailPanel :open="!!selectedVote" title="投票詳情" @close="selectedVote = null">
      <div v-if="selectedVote" class="flex flex-col" style="gap:14px">
        <div class="flex flex-wrap" style="gap:6px">
          <Badge :type="selectedVote.status">{{ selectedVote.status }}</Badge>
          <Badge :type="selectedVote.event_type ?? 'neutral'">{{ selectedVote.event_type || '—' }}</Badge>
          <Badge v-if="selectedVote.status === 'needs_review'" type="warning">需人工審核</Badge>
        </div>
        <div style="font-size:13px; color:#edf0f4; background:#21262f; padding:10px 12px; border-radius:8px; line-height:1.6">
          {{ selectedVote.instruction || '—' }}
        </div>
        <div class="flex items-center justify-between" style="padding:10px 12px; background:#033848; border-radius:8px; border:1px solid #06c8e840">
          <span style="font-size:13px; color:#8a97a8; font-weight:600">評分</span>
          <span class="font-mono font-bold" style="font-size:18px" :style="{ color: scoreColor(selectedVote.score) }">
            {{ selectedVote.score != null ? selectedVote.score.toFixed(1) : '—' }}
          </span>
        </div>
        <div v-if="selectedVote.score_reason" style="font-size:12px; color:#8a97a8; background:#21262f; padding:8px 12px; border-radius:8px; line-height:1.5">
          {{ selectedVote.score_reason }}
        </div>
        <div class="flex" style="gap:8px">
          <Btn variant="ghost" style="flex:1; justify-content:center; color:#00e676; border:1px solid #00e67640" @click="handleApprove(selectedVote.id)">
            手動 Approve
          </Btn>
          <Btn variant="danger" style="flex:1; justify-content:center" @click="handleReject(selectedVote.id)">
            手動 Reject
          </Btn>
        </div>
      </div>
    </DetailPanel>

    <!-- ── ConfirmDialog：停用/啟用確認 ── -->
    <ConfirmDialog
      :open="confirmToggle"
      :title="pendingTeacher?.is_active ? '確認停用師父' : '確認啟用師父'"
      :message="`確定要${pendingTeacher?.is_active ? '停用' : '啟用'} ${pendingTeacher?.name ?? ''} 嗎？`"
      :confirm-label="pendingTeacher?.is_active ? '停用' : '啟用'"
      :confirm-variant="pendingTeacher?.is_active ? 'danger' : 'primary'"
      @confirm="confirmDoToggle"
      @cancel="confirmToggle = false; pendingToggleId = null"
    />

    <!-- ── TeacherFormModal ── -->
    <Modal
      :open="showForm"
      :title="formMode === 'create' ? '新增師父' : `編輯 — ${formData.name}`"
      width="520px"
      @close="showForm = false"
    >
      <form class="flex flex-col" style="gap:14px" @submit.prevent="submitForm">

        <FormField label="名稱" required :error="formErrors.name">
          <input
            v-model="formData.name"
            :disabled="formMode === 'edit'"
            class="font-mono w-full border-0"
            style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box"
            :style="formMode === 'edit' ? { opacity: 0.5, cursor: 'not-allowed' } : {}"
            placeholder="shiba-gemini-flash"
          />
        </FormField>

        <FormField label="model_id" required :error="formErrors.model_id">
          <input v-model="formData.model_id" class="font-mono w-full border-0" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box" placeholder="gemini-2.5-flash" />
        </FormField>

        <FormField label="api_base" required :error="formErrors.api_base">
          <input v-model="formData.api_base" class="font-mono w-full border-0" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box" placeholder="https://generativelanguage.googleapis.com/v1beta" />
        </FormField>

        <div class="grid grid-cols-2" style="gap:10px">
          <FormField label="廠牌 (vendor)">
            <select v-model="formData.vendor" class="font-mono border-0 cursor-pointer" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; color-scheme:dark; outline:none; width:100%">
              <option v-for="v in ['google','xai','openai','mistral','anthropic','local','unknown']" :key="v" :value="v">{{ v }}</option>
            </select>
          </FormField>

          <FormField label="優先序 (priority)">
            <input v-model.number="formData.priority" type="number" class="font-mono border-0" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box" />
          </FormField>
        </div>

        <div class="grid grid-cols-2" style="gap:10px">
          <FormField label="每日 req 上限" :error="formErrors.daily_request_limit">
            <input v-model.number="formData.daily_request_limit" type="number" min="1" class="font-mono border-0" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box" />
          </FormField>

          <FormField label="每日 token 上限" hint="留空 = 無限制">
            <input v-model="formData.daily_token_limit" type="number" min="1" class="font-mono border-0" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; outline:none; width:100%; box-sizing:border-box" placeholder="留空無限制" />
          </FormField>
        </div>

        <FormField label="配額重置週期">
          <select v-model="formData.quota_reset_period" class="font-mono border-0 cursor-pointer" style="background:#21262f; border-radius:6px; padding:7px 10px; font-size:12px; color:#edf0f4; color-scheme:dark; outline:none; width:100%">
            <option value="daily">daily</option>
            <option value="weekly">weekly</option>
            <option value="monthly">monthly</option>
          </select>
        </FormField>

        <div class="flex items-center" style="gap:8px">
          <input id="chk_active" v-model="formData.is_active" type="checkbox" style="accent-color:#c084fc; width:14px; height:14px; cursor:pointer" />
          <label for="chk_active" class="font-mono" style="font-size:12px; color:#8a97a8; cursor:pointer">啟用</label>
        </div>

        <div class="flex" style="gap:8px; justify-content:flex-end; padding-top:4px; border-top:1px solid #21262f">
          <Btn variant="ghost" type="button" @click="showForm = false">取消</Btn>
          <Btn variant="primary" type="submit" :loading="formLoading">
            {{ formMode === 'create' ? '建立師父' : '儲存變更' }}
          </Btn>
        </div>
      </form>
    </Modal>
  </div>
</template>

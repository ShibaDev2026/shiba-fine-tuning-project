<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '../api/client'
import type { Column } from '../components/shared/DataTable.vue'
import SectionHeader   from '../components/shared/SectionHeader.vue'
import StatCard        from '../components/shared/StatCard.vue'
import Badge           from '../components/shared/Badge.vue'
import StatusDot       from '../components/shared/StatusDot.vue'
import DataTable       from '../components/shared/DataTable.vue'
import DetailPanel     from '../components/shared/DetailPanel.vue'
import Btn             from '../components/shared/Btn.vue'

interface Run {
  id: number
  adapter_block: number
  status: string
  sample_count: number | null
  ollama_model: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  adapter_path: string | null
  error_msg: string | null
}
interface TriggerBlock {
  approved_count?: number
  target?: number
  days_since_last_run?: number
  next_interval_days?: number
  last_run_at?: string | null
}
interface TriggerStatus {
  block1?: TriggerBlock
  block2?: TriggerBlock
  acceptance_rate?: number | null
}
interface OllamaModel { name: string; size?: string }
interface OllamaStatus {
  vram_used?: string
  loaded_models?: OllamaModel[]
  all_models?: OllamaModel[]
}

const FLOW_NODES = [
  { id:'sessions', label:'對話資料', sub:'sessions DB',    count:142,  unit:'筆',    color:'#40c4ff' },
  { id:'approved', label:'Approved', sub:'Layer 2 評分',   count:42,   unit:'筆',    color:'#c084fc' },
  { id:'dataset',  label:'Dataset',  sub:'Alpaca JSONL',   count:42,   unit:'rows',  color:'#f5c518' },
  { id:'lora',     label:'MLX LoRA', sub:'rank=16 訓練',   count:1,    unit:'run',   color:'#ffab40' },
  { id:'gguf',     label:'GGUF',     sub:'轉換壓縮',       count:3.8,  unit:'GB',    color:'#ffab40' },
  { id:'gate',     label:'Shadow Gate', sub:'95% CI 把關', count:72,   unit:'% win', color:'#00e676' },
  { id:'ollama',   label:'Ollama',   sub:'ollama create',  count:1,    unit:'model', color:'#00e676' },
]

const selected = ref<Run | null>(null)
const block = ref<1 | 2>(1)
const flowActive = ref(true)
const runs = ref<Run[]>([])
const triggerStatus = ref<TriggerStatus | null>(null)
const ollama = ref<OllamaStatus | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function fetchData() {
  loading.value = true
  error.value = null
  try {
    const [r, ts, ol] = await Promise.all([
      api.get<Run[]>('/finetune/runs'),
      api.get<TriggerStatus>('/finetune/trigger-status'),
      api.get<OllamaStatus>('/finetune/ollama'),
    ])
    runs.value = r
    triggerStatus.value = ts
    ollama.value = ol
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(fetchData)

const trigger = computed<TriggerBlock | null>(() => {
  const ts = triggerStatus.value
  if (!ts) return null
  return block.value === 1 ? (ts.block1 ?? null) : (ts.block2 ?? null)
})

async function handleTrigger() {
  await api.post(`/finetune/trigger/${block.value}`)
  await fetchData()
}

const runColumns: Column[] = [
  { key:'id',            label:'Run',        mono: true },
  { key:'adapter_block', label:'Block' },
  { key:'status',        label:'狀態' },
  { key:'sample_count',  label:'樣本',       mono: true },
  { key:'ollama_model',  label:'模型',       mono: true },
  { key:'created_at',    label:'建立時間',   mono: true },
]

// Pipeline 動畫節點佈局
const containerRef = ref<HTMLDivElement | null>(null)
const containerW = ref(700)
function updateWidth() {
  if (containerRef.value) containerW.value = containerRef.value.offsetWidth
}
onMounted(() => { nextTick(updateWidth); window.addEventListener('resize', updateWidth) })
onUnmounted(() => window.removeEventListener('resize', updateWidth))

const NODE_W = 80
const gap = computed(() => Math.max(30, (containerW.value - FLOW_NODES.length * NODE_W) / (FLOW_NODES.length - 1)))
const totalW = computed(() => FLOW_NODES.length * NODE_W + (FLOW_NODES.length - 1) * gap.value)

function nodeLeftPct(i: number) {
  const cx = i * (NODE_W + gap.value) + NODE_W / 2
  return `${(cx / totalW.value) * 100}%`
}
function lineLeftPct(i: number) {
  const x1 = i * (NODE_W + gap.value) + NODE_W / 2 + NODE_W / 2 - 4
  return `${(x1 / totalW.value) * 100}%`
}
function lineWidthPct(i: number) {
  const x1 = i * (NODE_W + gap.value) + NODE_W / 2 + NODE_W / 2 - 4
  const x2 = (i + 1) * (NODE_W + gap.value) + NODE_W / 2 - NODE_W / 2 + 4
  return `${((x2 - x1) / totalW.value) * 100}%`
}

// 訓練採納率顏色
const adoptionColor = computed(() => {
  const r = triggerStatus.value?.acceptance_rate
  if (r == null) return '#505c6e'
  return r >= 0.5 ? '#00e676' : '#ff5252'
})
const acceptanceRate = computed(() => triggerStatus.value?.acceptance_rate ?? null)

// 模型載入狀態判斷
function isLoaded(m: OllamaModel) {
  return (ollama.value?.loaded_models ?? []).some(l => l.name === m.name)
}

// 統計
const doneCount = computed(() => runs.value.filter(r => r.status === 'done').length)
const gateRejectedCount = computed(() => runs.value.filter(r => r.status === 'gate_rejected').length)

// PipelineFlow 背景漸層 / 動畫透過 style 驅動，watch 容器寬度
watch(containerW, () => {})  // 保留 reactive 觸發
</script>

<template>
  <div class="flex-1 flex flex-col" style="min-width:0">
    <SectionHeader
      title="Fine-tuning 管道"
      sub="Layer 3 · MLX LoRA → GGUF → Shadow Gate → Ollama 部署"
      accent="#ffab40"
    >
      <template #actions>
        <Btn :variant="block === 1 ? 'primary' : 'ghost'" @click="block = 1">block1</Btn>
        <Btn :variant="block === 2 ? 'primary' : 'ghost'" @click="block = 2">block2</Btn>
      </template>
    </SectionHeader>

    <div v-if="error" class="font-mono" style="color:#ff5252; font-size:12px; margin-bottom:8px">API 錯誤：{{ error }}</div>
    <div v-if="loading" class="font-mono" style="color:#505c6e; font-size:12px; margin-bottom:8px">載入中…</div>

    <!-- Stats row -->
    <div class="grid grid-cols-4" style="gap:10px; margin-bottom:18px">
      <StatCard label="訓練次數" :value="runs.length" sub="total runs" />
      <StatCard label="成功部署" :value="doneCount" sub="done" color="#00e676" />
      <StatCard label="Gate 拒絕" :value="gateRejectedCount" sub="shadow gate"
                :color="gateRejectedCount > 0 ? '#ff5252' : '#00e676'" />
      <StatCard
        label="現役模型"
        :value="ollama?.loaded_models?.[0]?.name?.split(':')[0] ?? '—'"
        :sub="ollama?.loaded_models?.[0]?.name ?? '無模型載入'"
        color="#ffab40"
      />
    </div>

    <!-- Pipeline Flow -->
    <div
      style="background:#191d24; border-radius:12px; padding:18px 20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div class="flex items-center justify-between" style="margin-bottom:20px">
        <div
          class="font-mono uppercase"
          style="font-size:11px; color:#505c6e; letter-spacing:0.06em"
        >
          資料流示意
        </div>
        <button
          @click="flowActive = !flowActive"
          class="font-mono border cursor-pointer transition-all duration-150"
          style="background:none; border:1px solid #2c333e; border-radius:6px; font-size:11px; padding:3px 10px"
          :style="{ color: flowActive ? '#00e676' : '#505c6e' }"
        >
          {{ flowActive ? '● 動畫中' : '○ 暫停' }}
        </button>
      </div>

      <!-- Flow Canvas -->
      <div ref="containerRef" class="relative w-full" style="min-height:208px">
        <!-- Connector lines（背景軌道 + rainbow 動畫） -->
        <div
          v-for="(node, i) in FLOW_NODES.slice(0, -1)"
          :key="node.id + '-line'"
          class="absolute"
          style="top:58px; height:4px; border-radius:2px; z-index:1"
          :style="{
            left: lineLeftPct(i),
            width: lineWidthPct(i),
            background: flowActive
              ? 'linear-gradient(90deg, #06c8e8, #00e676, #f5c518, #ffab40, #ff5252, #c084fc, #06c8e8)'
              : '#2c333e',
            backgroundSize: flowActive ? '300% 100%' : undefined,
            animation: flowActive ? 'flow-rainbow 2s linear infinite' : 'none',
          }"
        >
          <div
            v-if="flowActive"
            class="absolute rounded-full"
            style="top:50%; transform:translateY(-50%); width:8px; height:8px; background:white; box-shadow:0 0 8px 2px rgba(255,255,255,0.8)"
            :style="{
              animation: `dot-travel ${1.4 + i * 0.18}s linear infinite`,
              animationDelay: `${i * 0.22}s`,
            }"
          />
        </div>

        <!-- Nodes -->
        <div
          v-for="(node, i) in FLOW_NODES"
          :key="node.id"
          class="absolute flex flex-col items-center"
          style="top:24px; gap:6px; z-index:2"
          :style="{
            left: nodeLeftPct(i),
            transform: 'translateX(-50%)',
            width: `${NODE_W}px`,
          }"
        >
          <div
            class="flex items-center justify-center relative rounded-full"
            style="width:44px; height:44px; background:#191d24; transition:box-shadow 300ms"
            :style="{
              border: `2px solid ${node.color}`,
              boxShadow: flowActive ? `0 0 12px 2px ${node.color}40` : 'none',
              animation: flowActive ? 'node-glow 2s ease-in-out infinite' : 'none',
              animationDelay: `${i * 0.2}s`,
            }"
          >
            <span
              class="font-mono font-semibold text-center"
              style="font-size:10px; line-height:1.2"
              :style="{ color: node.color }"
            >
              {{ node.count }}<br /><span style="font-size:8px">{{ node.unit }}</span>
            </span>
          </div>
          <div class="text-center">
            <div
              class="font-body font-semibold whitespace-nowrap"
              style="font-size:11px; color:#edf0f4"
            >
              {{ node.label }}
            </div>
            <div
              class="font-mono whitespace-nowrap"
              style="font-size:9px; color:#505c6e; margin-top:1px"
            >
              {{ node.sub }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Trigger Status -->
    <div
      style="background:#191d24; border-radius:12px; padding:18px 20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center" style="gap:10px">
          <div
            class="font-mono uppercase"
            style="font-size:11px; color:#505c6e; letter-spacing:0.06em"
          >
            block{{ block }} 觸發狀態
          </div>
          <Badge
            v-if="(trigger?.approved_count ?? 0) >= (trigger?.target ?? 30)"
            type="warning"
          >
            ⚡ 達標可訓練
          </Badge>
          <Badge v-else type="approved">✓ 待機</Badge>
        </div>
        <Btn variant="ghost" @click="handleTrigger">手動觸發</Btn>
      </div>
      <div style="font-size:13px; color:#8a97a8; margin-top:8px">
        {{ trigger
          ? `上次訓練：${trigger.last_run_at ?? '無紀錄'} · 距今 ${trigger.days_since_last_run ?? '—'} 天`
          : '載入中…' }}
      </div>

      <!-- Trigger Stats 3 欄 -->
      <div class="grid grid-cols-3" style="gap:12px; margin-top:14px">
        <!-- 採納率 -->
        <div
          class="flex flex-col"
          style="background:#111318; border-radius:10px; padding:14px 16px; gap:8px"
          :style="{ border: `1px solid ${adoptionColor}30` }"
        >
          <div
            class="font-mono uppercase"
            style="font-size:10px; color:#505c6e; letter-spacing:0.06em"
          >
            採納率
          </div>
          <div
            class="font-display font-bold"
            style="font-size:36px; line-height:1; letter-spacing:-0.03em"
            :style="{ color: adoptionColor }"
          >
            {{ acceptanceRate != null ? (acceptanceRate * 100).toFixed(0) : '—' }}<span style="font-size:16px; font-weight:400">%</span>
          </div>
          <div class="w-full rounded-full" style="height:4px; background:#2c333e">
            <div
              class="h-full rounded-full transition-all"
              style="transition-duration:600ms"
              :style="{
                width: `${acceptanceRate != null ? acceptanceRate * 100 : 0}%`,
                background: adoptionColor,
              }"
            />
          </div>
          <div class="font-mono" style="font-size:10px; color:#505c6e">
            閾值 50% ·
            {{ acceptanceRate == null ? '—' : acceptanceRate >= 0.5 ? '✓ 正常' : '✗ 退化' }}
          </div>
        </div>

        <!-- Approved 樣本 -->
        <div
          class="flex flex-col"
          style="background:#111318; border-radius:10px; padding:14px 16px; gap:8px; border:1px solid #40c4ff30"
        >
          <div
            class="font-mono uppercase"
            style="font-size:10px; color:#505c6e; letter-spacing:0.06em"
          >
            Approved 樣本
          </div>
          <div
            class="font-display font-bold"
            style="font-size:36px; line-height:1; letter-spacing:-0.03em; color:#40c4ff"
          >
            {{ trigger?.approved_count ?? 0 }}
            <span style="font-size:14px; font-weight:400; color:#505c6e">
              / {{ trigger?.target ?? 30 }}
            </span>
          </div>
          <div class="w-full rounded-full" style="height:4px; background:#2c333e">
            <div
              class="h-full rounded-full"
              style="background:#40c4ff"
              :style="{
                width: `${Math.min(100, ((trigger?.approved_count ?? 0) / (trigger?.target ?? 30)) * 100)}%`,
              }"
            />
          </div>
          <div class="font-mono" style="font-size:10px; color:#505c6e">
            block{{ block }} ·
            {{ (trigger?.approved_count ?? 0) >= (trigger?.target ?? 30)
              ? '✓ 達標'
              : `差 ${(trigger?.target ?? 30) - (trigger?.approved_count ?? 0)} 筆` }}
          </div>
        </div>

        <!-- Ebbinghaus -->
        <div
          class="flex flex-col"
          style="background:#111318; border-radius:10px; padding:14px 16px; gap:8px; border:1px solid #c084fc30"
        >
          <div
            class="font-mono uppercase"
            style="font-size:10px; color:#505c6e; letter-spacing:0.06em"
          >
            Ebbinghaus
          </div>
          <div
            class="font-display font-bold"
            style="font-size:36px; line-height:1; letter-spacing:-0.03em; color:#c084fc"
          >
            {{ trigger?.days_since_last_run ?? 0 }}
            <span style="font-size:16px; font-weight:400">d</span>
          </div>
          <div class="flex" style="gap:3px; margin-top:2px">
            <div
              v-for="d in [1, 2, 4, 7, 15, 30]"
              :key="d"
              class="flex-1 rounded-sm transition-colors"
              style="height:4px; transition-duration:300ms"
              :style="{
                background: (trigger?.days_since_last_run ?? 0) >= d ? '#c084fc' : '#2c333e',
              }"
            />
          </div>
          <div class="font-mono" style="font-size:10px; color:#505c6e">
            下次觸發：{{ trigger?.next_interval_days ?? 30 }}d 間隔
          </div>
        </div>
      </div>
    </div>

    <!-- Ollama Resources -->
    <div
      style="background:#191d24; border-radius:12px; padding:16px 20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div class="flex items-center justify-between" style="margin-bottom:12px">
        <div
          class="font-mono uppercase"
          style="font-size:11px; color:#505c6e; letter-spacing:0.06em"
        >
          Ollama 資源
        </div>
        <div class="flex font-mono" style="gap:12px; font-size:10px; color:#505c6e">
          <span>VRAM: {{ ollama?.vram_used ?? '—' }}</span>
          <span>載入：{{ (ollama?.loaded_models ?? []).length }} 個</span>
        </div>
      </div>
      <div class="flex flex-col" style="margin-top:4px; gap:4px">
        <div
          v-if="(ollama?.all_models ?? []).length === 0"
          class="font-mono"
          style="font-size:12px; color:#505c6e"
        >
          無模型資料（Ollama 未啟動？）
        </div>
        <div
          v-for="m in ollama?.all_models ?? []"
          :key="m.name"
          class="flex items-center justify-between"
          style="padding:7px 10px; background:#111318; border-radius:8px"
        >
          <div class="flex items-center" style="gap:8px">
            <StatusDot :state="isLoaded(m) ? 'active' : 'inactive'" />
            <span
              class="font-mono"
              style="font-size:12px"
              :style="{ color: isLoaded(m) ? '#edf0f4' : '#8a97a8' }"
            >
              {{ m.name }}
            </span>
            <Badge v-if="isLoaded(m)" type="approved">載入中</Badge>
          </div>
          <span class="font-mono" style="font-size:11px; color:#505c6e">{{ m.size ?? '—' }}</span>
        </div>
      </div>
    </div>

    <!-- Run History -->
    <div
      style="background:#191d24; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.04)"
    >
      <div
        class="font-mono"
        style="padding:10px 16px; border-bottom:1px solid #21262f; font-size:11px; color:#505c6e"
      >
        訓練執行紀錄 · 點擊查看詳情
      </div>
      <DataTable
        :columns="runColumns"
        :rows="runs"
        :selected-id="selected?.id ?? null"
        @select="(r: Run) => selected = r"
      >
        <template #cell-id="{ value }">#{{ value }}</template>
        <template #cell-adapter_block="{ value }">
          <Badge :type="value === 1 ? 'info' : 'claude'">block{{ value }}</Badge>
        </template>
        <template #cell-status="{ value }">
          <Badge :type="value">{{ value }}</Badge>
        </template>
        <template #cell-sample_count="{ value }">
          <span style="color:#00e676">{{ value ?? '—' }}</span>
        </template>
        <template #cell-ollama_model="{ value }">
          <span v-if="value" style="color:#ffab40; font-size:10px">{{ value.split(':')[1] }}</span>
          <span v-else style="color:#505c6e">—</span>
        </template>
        <template #cell-created_at="{ value }">{{ value ? value.slice(0, 16) : '—' }}</template>
      </DataTable>
    </div>

    <!-- Detail Panel -->
    <DetailPanel :open="!!selected" title="訓練執行詳情" @close="selected = null">
      <div v-if="selected" class="flex flex-col" style="gap:14px">
        <div class="flex flex-wrap" style="gap:6px">
          <Badge :type="selected.adapter_block === 1 ? 'info' : 'claude'">block{{ selected.adapter_block }}</Badge>
          <Badge :type="selected.status">{{ selected.status }}</Badge>
        </div>
        <div
          v-for="row in [
            { k:'Run ID',     v:`#${selected.id}` },
            { k:'樣本數',     v:selected.sample_count ?? '—' },
            { k:'開始時間',   v:selected.started_at ?? selected.created_at ?? '—' },
            { k:'完成時間',   v:selected.finished_at ?? '—' },
            { k:'部署模型',   v:selected.ollama_model || '— (未部署)' },
            { k:'Adapter 路徑', v:selected.adapter_path || '—' },
            { k:'錯誤訊息',   v:selected.error_msg || '—' },
          ]"
          :key="row.k"
          class="flex flex-col"
          style="gap:3px"
        >
          <div class="font-mono" style="font-size:11px; color:#505c6e">{{ row.k }}</div>
          <div class="font-mono" style="font-size:13px; color:#edf0f4; word-break:break-all">{{ row.v }}</div>
        </div>
      </div>
    </DetailPanel>
  </div>
</template>

<style>
@keyframes flow-rainbow {
  0%   { background-position: 0% 50%; }
  100% { background-position: 300% 50%; }
}
@keyframes dot-travel {
  0%   { left: 0%;   opacity: 0; }
  5%   { opacity: 1; }
  95%  { opacity: 1; }
  100% { left: 100%; opacity: 0; }
}
@keyframes node-glow {
  0%,100% { box-shadow: 0 0 0 0 rgba(6,200,232,0); }
  50%     { box-shadow: 0 0 12px 3px rgba(6,200,232,0.35); }
}
</style>

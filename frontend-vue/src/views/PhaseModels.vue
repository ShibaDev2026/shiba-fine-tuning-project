<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'
import SectionHeader from '../components/shared/SectionHeader.vue'

// ── 型別 ────────────────────────────────────────────────────
interface Snapshot {
  description: string
  ollama_tag: string | null
  hf_repo: string | null
  inference: Record<string, unknown> | null
  prompt: { system: string | null; user_template: string | null } | null
  training: Record<string, unknown> | null
  meta: Record<string, unknown>
  maintenance: { yaml_version: number; added_at: string; notes: string }
}

interface ModelRow {
  id: number
  model_name: string
  version_seq: number
  is_current: number
  content_hash: string
  role: string
  display_name: string
  change_kind: string
  recorded_at: string
  snapshot: Snapshot
}

// ── 狀態 ────────────────────────────────────────────────────
const models      = ref<ModelRow[]>([])
const routerCfg   = ref<Record<string, { value: string }>>({})
const loading     = ref(true)
const error       = ref<string | null>(null)
// 展開 Inference/Meta/System Prompt 的卡片 set（點擊卡片 header 區域觸發三個一起展開/收合）
const expandedCards = ref<Set<string>>(new Set())
function toggleCard(name: string) {
  if (expandedCards.value.has(name)) expandedCards.value.delete(name)
  else expandedCards.value.add(name)
}

// ── 角色設定 ─────────────────────────────────────────────────
const ROLES = [
  { key: 'classifier',    label: '分類器',     en: 'Classifier',    color: '#f5c518', cfgKey: 'classifier_model_yaml' },
  { key: 'compressor',    label: '壓縮器',     en: 'Compressor',    color: '#40c4ff', cfgKey: 'compressor_model_yaml' },
  { key: 'responder',     label: '回應模型',   en: 'Responder',     color: '#4ade80', cfgKey: 'responder_model_yaml' },
  { key: 'training_base', label: '訓練基底',   en: 'Training Base', color: '#ffab40', cfgKey: 'training_base_block1_yaml' },
]

// ── 計算屬性 ─────────────────────────────────────────────────
const byRole = computed(() => {
  return ROLES.map(r => {
    const items = models.value.filter(m => m.role === r.key)
    const activeStem = routerCfg.value[r.cfgKey]?.value ?? null

    // 排序：選取中的排前面，其餘按 display_name
    const sorted = [...items].sort((a, b) => {
      if (activeStem) {
        if (a.model_name === activeStem) return -1
        if (b.model_name === activeStem) return 1
      }
      return a.display_name.localeCompare(b.display_name)
    })
    return { ...r, items: sorted, activeStem }
  })
})

// ── API ──────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value = null
  try {
    const [reg, cfg] = await Promise.all([
      api.get<ModelRow[]>('/models/registry'),
      api.get<Record<string, { value: string }>>('/router-config'),
    ])
    models.value   = reg
    routerCfg.value = cfg
  } catch (e: unknown) {
    error.value = (e as Error).message ?? '載入失敗'
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ── helpers ──────────────────────────────────────────────────
function paramPills(obj: Record<string, unknown>): { k: string; v: string }[] {
  return Object.entries(obj)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({ k, v: Array.isArray(v) ? JSON.stringify(v) : String(v) }))
}

function shortHash(h: string) { return h.slice(0, 8) }
</script>

<template>
  <div>
    <SectionHeader
      title="模型設置"
      subtitle="Configuration Models · 各角色當前 yaml 版本"
    />

    <div v-if="loading" style="color:#9aafcc; padding:40px 0; text-align:center; font-size:16px">
      載入中…
    </div>
    <div v-else-if="error" style="color:#f87171; padding:16px; font-size:16px">{{ error }}</div>

    <!-- 4-column grid -->
    <div
      v-else
      style="display:grid; grid-template-columns:repeat(4,1fr); gap:16px; align-items:start"
    >
      <!-- 每個 role column -->
      <div v-for="group in byRole" :key="group.key" style="display:flex; flex-direction:column; gap:12px; min-width:0">

        <!-- role header -->
        <div style="display:flex; align-items:center; gap:8px; padding-bottom:4px">
          <span
            style="width:3px; height:16px; border-radius:2px; display:inline-block; flex-shrink:0"
            :style="{ background: group.color }"
          />
          <div>
            <div class="font-mono" style="font-size:14px; font-weight:700; text-transform:uppercase; letter-spacing:.08em"
                 :style="{ color: group.color }">{{ group.en }}</div>
            <div style="font-size:13px; color:#9aafcc">{{ group.label }}</div>
          </div>
        </div>

        <!-- model cards（responder 有多張時垂直堆疊於 column 內）-->
        <div
          v-for="(m, idx) in group.items"
          :key="m.model_name"
          style="border-radius:10px; overflow:hidden; display:flex; flex-direction:column; cursor:pointer; min-width:0"
          :style="{
            background: '#0d1016',
            border: `1px solid ${idx === 0 ? group.color + '99' : '#2a3340'}`,
            opacity: group.items.length > 1 && idx > 0 ? '0.72' : '1',
            flex: '0 0 auto',
          }"
          @click.stop="toggleCard(m.model_name)"
        >
          <!-- 頂部色條 -->
          <div style="height:2px; flex-shrink:0" :style="{ background: group.color, opacity: idx === 0 ? '1' : '0.35' }" />

          <div style="padding:16px; display:flex; flex-direction:column; gap:14px; flex:1">

            <!-- 第一列：模型名稱 + active badge -->
            <div style="display:flex; align-items:flex-start; gap:8px">
              <div style="flex:1; min-width:0">
                <div style="font-size:16px; font-weight:600; color:#dce6ee; line-height:1.35; word-break:break-word">
                  {{ m.display_name }}
                </div>
                <div class="font-mono" style="font-size:16px; color:#5a6878; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis">
                  {{ m.model_name }}
                </div>
              </div>
              <span
                v-if="group.activeStem === m.model_name"
                class="font-mono"
                style="flex-shrink:0; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; padding:2px 6px; border-radius:4px"
                :style="{ color: group.color, background: group.color + '1a', border: `1px solid ${group.color}44` }"
              >ACTIVE</span>
              <span
                v-else-if="group.items.length > 1"
                style="flex-shrink:0; font-size:12px; color:#7a8fa8; padding:2px 6px; border-radius:4px; border:1px solid #21262f; font-family:monospace"
              >STANDBY</span>
            </div>

            <!-- 第二列：描述 -->
            <p
              v-if="m.snapshot.description"
              style="margin:0; font-size:14px; color:#9aafc4; line-height:1.55"
            >
              {{ m.snapshot.description }}
            </p>

            <!-- 第三列：版本 + tag/repo + hash -->
            <div style="display:flex; flex-wrap:wrap; align-items:center; gap:6px">
              <span
                class="font-mono"
                style="font-size:14px; padding:3px 8px; border-radius:5px; font-weight:600"
                :style="{ color: group.color, background: group.color + '18', border: `1px solid ${group.color}33` }"
              >v{{ m.version_seq }}</span>
              <span
                v-if="m.snapshot.ollama_tag"
                class="font-mono"
                style="font-size:16px; color:#40c4ff; background:#071520; padding:2px 7px; border-radius:4px; border:1px solid #0e2a3a"
              >{{ m.snapshot.ollama_tag }}</span>
              <span
                v-else-if="m.snapshot.hf_repo"
                class="font-mono"
                style="font-size:16px; color:#c084fc; background:#100b1f; padding:2px 7px; border-radius:4px; border:1px solid #20104a; word-break:break-all"
              >{{ m.snapshot.hf_repo }}</span>
              <span class="font-mono" style="font-size:12px; color:#506070">{{ shortHash(m.content_hash) }}</span>
            </div>

            <!-- Inference / Training / Meta / System Prompt — 點卡片一次展開全部 -->
            <template v-if="expandedCards.has(m.model_name)">

              <!-- Inference params -->
              <div v-if="m.snapshot.inference">
                <div class="font-mono" style="font-size:11px; color:#647888; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">
                  Inference
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:4px">
                  <span
                    v-for="p in paramPills(m.snapshot.inference)"
                    :key="p.k"
                    class="font-mono"
                    style="font-size:12px; background:#131820; border:1px solid #1e2530; border-radius:4px; padding:2px 6px; color:#9aafcc; white-space:nowrap"
                  ><span style="color:#7a8fa8">{{ p.k }}:</span> {{ p.v }}</span>
                </div>
              </div>

              <!-- Training params -->
              <div v-if="m.snapshot.training">
                <div class="font-mono" style="font-size:11px; color:#647888; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">
                  Training
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:4px">
                  <span
                    v-for="p in paramPills(m.snapshot.training)"
                    :key="p.k"
                    class="font-mono"
                    style="font-size:12px; background:#131820; border:1px solid #1e2530; border-radius:4px; padding:2px 6px; color:#9aafcc; white-space:nowrap"
                  ><span style="color:#7a8fa8">{{ p.k }}:</span> {{ p.v }}</span>
                </div>
              </div>

              <!-- Meta -->
              <div v-if="m.snapshot.meta">
                <div class="font-mono" style="font-size:11px; color:#647888; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">
                  Meta
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:4px">
                  <span
                    v-for="p in paramPills(m.snapshot.meta)"
                    :key="p.k"
                    class="font-mono"
                    style="font-size:12px; background:#131820; border:1px solid #1e2530; border-radius:4px; padding:2px 6px; color:#9aafcc; white-space:nowrap"
                  ><span style="color:#7a8fa8">{{ p.k }}:</span> {{ p.v }}</span>
                </div>
              </div>

              <!-- System Prompt -->
              <div v-if="m.snapshot.prompt?.system">
                <div class="font-mono" style="font-size:11px; color:#647888; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px">
                  System Prompt
                </div>
                <pre style="margin:0; font-size:12px; color:#9aafc4; background:#090c10; padding:10px; border-radius:6px; border:1px solid #1a1f28; white-space:pre-wrap; word-break:break-word; line-height:1.6; font-family:monospace">{{ m.snapshot.prompt.system }}</pre>
              </div>

            </template>

            <!-- 收合時顯示的提示 -->
            <div v-else style="font-size:12px; color:#3a4a58; font-family:monospace; letter-spacing:.03em">
              點擊展開詳細參數 ↓
            </div>

            <!-- 底部：maintenance -->
            <div style="border-top:1px solid #141920; padding-top:10px; display:flex; justify-content:space-between; align-items:center">
              <span class="font-mono" style="font-size:12px; color:#506070">
                yaml v{{ m.snapshot.maintenance.yaml_version }} · {{ m.snapshot.maintenance.added_at }}
              </span>
              <span class="font-mono" style="font-size:12px; color:#506070">
                {{ m.change_kind }}
              </span>
            </div>

          </div>
        </div>
        <!-- /card -->

      </div>
      <!-- /column -->
    </div>
    <!-- /grid -->

  </div>
</template>

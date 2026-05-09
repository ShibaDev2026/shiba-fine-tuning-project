// router store：集中管理 Layer 0 模型切換 + offline kill switch UI 狀態
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { routerApi, type RouterStatus, type ModelByRole } from '../api/router'
import { useToastStore } from './toast'

const ROLES = ['classifier', 'compressor', 'responder'] as const
type Role = (typeof ROLES)[number]

export const useRouterStore = defineStore('router', () => {
  const toast = useToastStore()

  const status = ref<RouterStatus | null>(null)
  // 各 role 可選 yaml 清單（含 status: installed/not_downloaded）
  const optionsByRole = ref<Record<Role, ModelByRole[]>>({
    classifier: [],
    compressor: [],
    responder: [],
  })
  const loading = ref(false)
  // 切換中 role；用於 dropdown 顯示 spinner / 鎖 UI
  const switching = ref<string | null>(null)

  const ollamaOnline = computed(() => status.value?.ollama_status === 'online')

  // 初始抓 status + 三個 role 的 yaml 清單
  async function refresh() {
    loading.value = true
    try {
      const [st, cls, cmp, rsp] = await Promise.all([
        routerApi.status(),
        routerApi.byRole('classifier'),
        routerApi.byRole('compressor'),
        routerApi.byRole('responder'),
      ])
      status.value = st
      optionsByRole.value = { classifier: cls, compressor: cmp, responder: rsp }
    } catch (e) {
      toast.push(`抓取 router 狀態失敗：${(e as Error).message}`, 'error')
    } finally {
      loading.value = false
    }
  }

  // 切換某 role 的 active model
  async function switchModel(role: Role, stem: string) {
    if (status.value?.roles[role]?.stem === stem) return
    switching.value = role
    toast.push(`載入中（首次切換需等 Ollama swap，~30s）…`, 'info')
    try {
      await routerApi.putConfig(`${role}_model_yaml`, stem)
      toast.push(`${role} 已切換至 ${stem}`, 'success')
      await refresh()
    } catch (e) {
      toast.push(`切換失敗：${(e as Error).message}`, 'error')
    } finally {
      switching.value = null
    }
  }

  // 切換 offline kill switch
  async function toggleOllama(online: boolean) {
    switching.value = 'ollama_status'
    try {
      await routerApi.putConfig('ollama_status', online ? 'online' : 'offline')
      toast.push(online ? 'Ollama 已啟用' : 'Ollama 已停用（全走 Claude）', 'success')
      await refresh()
    } catch (e) {
      toast.push(`切換失敗：${(e as Error).message}`, 'error')
    } finally {
      switching.value = null
    }
  }

  // Reload 某 role yaml（重新讀檔 → 更新 snapshot）
  async function reload(role: Role) {
    switching.value = role
    try {
      const r = await routerApi.reload(`${role}_model_yaml`)
      const s = r.sync_stats
      const changed = s.created + s.modified + s.restored + s.removed
      toast.push(
        changed > 0
          ? `${role} yaml 已重載（${changed} 變更）`
          : `${role} yaml 無變動`,
        'success',
      )
      await refresh()
    } catch (e) {
      toast.push(`reload 失敗：${(e as Error).message}`, 'error')
    } finally {
      switching.value = null
    }
  }

  return {
    status,
    optionsByRole,
    loading,
    switching,
    ollamaOnline,
    refresh,
    switchModel,
    toggleOllama,
    reload,
  }
})

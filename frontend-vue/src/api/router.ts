// router 端點封裝（Step 4 後端新增的 5 個端點）
import { api } from './client'

// ── 型別 ────────────────────────────────────────────────
export type ModelStatus = 'installed' | 'not_downloaded' | 'no_ollama_tag'

export interface ModelByRole {
  stem: string
  display_name: string
  ollama_tag: string | null
  status: ModelStatus
}

export interface ModelEntry {
  stem: string
  display_name: string
  ollama_tag: string
  role: string
}

export interface InstalledResponse {
  ollama_reachable: boolean
  yaml_configured: ModelEntry[]
  yaml_orphan: ModelEntry[]
  installed_no_yaml: { ollama_tag: string }[]
}

export interface RoleStatus {
  stem: string
  display_name: string
  snapshot_at: string | null
  yaml_exists: boolean
  yaml_modified: boolean
}

export interface RouterStatus {
  ollama_online: boolean
  ollama_status: 'online' | 'offline'
  classifier_model: string | null
  local_model: string | null
  router_enabled: boolean
  roles: Record<string, RoleStatus>
}

export interface SyncStats {
  created: number
  modified: number
  restored: number
  removed: number
  unchanged: number
}

// ── API ────────────────────────────────────────────────
export const routerApi = {
  status: () => api.get<RouterStatus>('/router/status'),

  installed: () => api.get<InstalledResponse>('/router/models/installed'),

  byRole: (role: string) =>
    api.get<ModelByRole[]>(`/router/models/by-role?role=${encodeURIComponent(role)}`),

  putConfig: (key: string, value: string) =>
    api.put<{ ok: boolean; key: string; value: string }>('/router/config', { key, value }),

  reload: (key: string) =>
    api.post<{ ok: boolean; key: string; stem: string; sync_stats: SyncStats }>(
      '/router/config/reload',
      { key },
    ),
}

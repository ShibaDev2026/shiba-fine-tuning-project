// PhaseMemory / PhaseRouter 共用的日期 query 建構器
import type { DateMode } from '../components/shared/DateFilterBar.vue'

function iso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function buildDateQS(mode: DateMode, from: string, to: string): string {
  const now = new Date()
  if (mode === 'today') {
    const t = iso(now)
    return `date_from=${t}&date_to=${t}`
  }
  if (mode === '7d') {
    const d7 = new Date(now)
    d7.setDate(d7.getDate() - 6)
    return `date_from=${iso(d7)}`
  }
  if (mode === 'custom') {
    const parts: string[] = []
    if (from) parts.push(`date_from=${from}`)
    if (to)   parts.push(`date_to=${to}`)
    return parts.join('&')
  }
  return ''
}

// 統一時間格式（Router + Memory 共用）
// DB 存 UTC，加 'Z' 後讓 Date 解析為 UTC 再轉本地時區顯示
export function fmtDT(v: string | null | undefined): string {
  if (!v) return '—'
  const normalized = v.includes('Z') || v.includes('+') ? v : v.replace(' ', 'T') + 'Z'
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return v.slice(0, 19).replace(/-/g, '/')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

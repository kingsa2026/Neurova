import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WorkLogEntry {
  log_id: string
  user_id: string
  agent_id: string
  title: string
  content: string
  category: string
  tags: string[]
  duration_minutes?: number
  created_at: number
}

export interface WorkLogCreate {
  title: string
  content?: string
  category?: string
  tags?: string[]
  duration_minutes?: number
}

export interface DailySummary {
  date: string
  total_logs: number
  total_duration: number
  categories: Record<string, number>
  tags: Record<string, number>
}

export interface WeeklyReport {
  week_start: string
  week_end: string
  total_logs: number
  total_duration: number
  daily_breakdown: DailySummary[]
  top_categories: Record<string, number>
  top_tags: Record<string, number>
}

export interface WorkLogStats {
  total_logs: number
  total_duration: number
  by_category: Record<string, number>
  by_tag: Record<string, number>
  by_day: Record<string, number>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/logs-api'

/** Create a work log entry. */
export function createWorkLog(data: WorkLogCreate) {
  return api.post<ApiResponse<WorkLogEntry>>(BASE, data)
}

/** List work logs. */
export function getWorkLogs(params?: { category?: string; tag?: string; start_date?: string; end_date?: string; limit?: number }) {
  return api.get<ApiResponse<WorkLogEntry[]>>(BASE, { params })
}

/** Get daily summary. */
export function getDailySummary(date?: string) {
  return api.get<ApiResponse<DailySummary>>(`${BASE}/daily-summary`, { params: date ? { date } : undefined })
}

/** Get weekly report. */
export function getWeeklyReport(weekOffset = 0) {
  return api.get<ApiResponse<WeeklyReport>>(`${BASE}/weekly-report`, { params: { week_offset: weekOffset } })
}

/** Get work log statistics. */
export function getWorkLogStats() {
  return api.get<ApiResponse<WorkLogStats>>(`${BASE}/stats`)
}

/** Export work logs. */
export function exportWorkLogs(params?: { format?: 'json' | 'csv'; start_date?: string; end_date?: string }) {
  return api.get<ApiResponse<{ logs: WorkLogEntry[] }>>(`${BASE}/export`, { params })
}

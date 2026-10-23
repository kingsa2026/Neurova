import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// 质量事件与指标（人工接管 / 轮次完成态）
// ---------------------------------------------------------------------------

export type TakeoverEventType = 'human_takeover_started' | 'human_takeover_ended'

export interface QualityEvent {
  event_id: string
  event_type: string
  session_id: string
  source: string
  source_event_id: string
  reason_code: string
  occurred_at: string
  duplicate: boolean
}

export interface TakeoverState {
  session_id: string
  active: boolean
  /** false = 窗口内没有任何接管事件，不能读成「确认未接管」。 */
  observed: boolean
  last_event: Record<string, string> | null
}

export interface QualityMetricsSummary {
  measure_state?: string
  window_seconds?: number
  turns?: number
  sessions?: number
  outcomes?: Record<string, number>
  human_takeover_rate?: number | null
  safety_refusal_rate?: number | null
  insufficient_evidence_rate?: number | null
  tool_failure_rate?: number | null
  unknown_outcome_rate?: number | null
  takeover_sessions?: number
  takeover_events?: number
  takeover_sources?: Record<string, number>
  takeover_channel_capability?: { supported: string[]; unsupported: string[] }
  missing_reason?: string
}

export interface RecordTakeoverPayload {
  event_type: TakeoverEventType
  session_id: string
  agent_id?: string
  channel?: string
  source?: 'channel_event' | 'console_mark' | 'api'
  source_event_id?: string
  actor_id?: string
  reason_code?: string
}

const BASE = '/quality'

export function recordHumanTakeover(payload: RecordTakeoverPayload) {
  return api.post<ApiResponse<QualityEvent>>(`${BASE}/outcomes`, payload)
}

export function getSessionTakeoverState(sessionId: string) {
  return api.get<ApiResponse<TakeoverState>>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/takeover`,
  )
}

/** 会话质量窗口读数（管理员运营面板消费；没有分母的率返回 null）。 */
export function getQualityMetrics(windowSeconds = 7 * 86400) {
  return api.get<ApiResponse<QualityMetricsSummary>>(`${BASE}/metrics`, {
    params: { window_seconds: windowSeconds },
  })
}

import api from '@/api'

// ---------------------------------------------------------------------------
// Types
//
// 契约注记（2026-09-12 对齐后端实测）：
// - GET /negative-screen 与 POST /negative-screen/test 返回**裸对象**（非信封）；
//   PUT/DELETE 与 /notifications/push-statistics 返回 {code,message,data} 信封。
// - GET 不回传明文 auth_code（安全收口），仅 masked_auth_code 供 UI 展示已配置状态。
// ---------------------------------------------------------------------------

export interface NegativeScreenConfig {
  user_id: string
  enabled: boolean
  push_url: string
  masked_auth_code?: string | null
}

export interface UpdateNegativeScreenConfig {
  /** 省略或留空 = 保留存量授权码（后端语义），渠道卡开关只 PUT {enabled} */
  auth_code?: string
  enabled?: boolean
  push_url?: string
}

interface Envelope<T> {
  code: number
  message: string
  data: T
  request_id?: string
}

export interface UpdateNegativeScreenResult {
  user_id: string
  masked_auth_code?: string | null
  enabled: boolean
}

export interface TestPushRequest {
  task_name?: string
  task_content?: string
  task_result?: string
}

export interface TestPushResponse {
  success: boolean
  task_id?: string | null
  response_code?: string | null
  error?: string | null
}

export interface PushStatistics {
  total_task_notifications: number
  pushed_to_negative_screen: number
  push_failed: number
  push_rate: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/negative-screen'

/** Get negative screen configuration (bare object, no plaintext auth_code). */
export function getNegativeScreenConfig() {
  return api.get<NegativeScreenConfig>(BASE)
}

/** Update negative screen configuration. */
export function updateNegativeScreenConfig(data: UpdateNegativeScreenConfig) {
  return api.put<Envelope<UpdateNegativeScreenResult>>(BASE, data)
}

/** Test negative screen push (bare object; error carries the upstream gateway message). */
export function testNegativeScreenPush(data: TestPushRequest) {
  return api.post<TestPushResponse>(`${BASE}/test`, data)
}

/** Delete negative screen configuration. */
export function deleteNegativeScreenConfig() {
  return api.delete<Envelope<{ user_id: string }>>(BASE)
}

/** Push statistics shown on the negative screen settings card. */
export function getPushStatistics() {
  return api.get<Envelope<PushStatistics>>('/notifications/push-statistics')
}

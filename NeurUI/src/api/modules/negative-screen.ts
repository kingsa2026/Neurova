import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NegativeScreenConfig {
  user_id: string
  auth_code?: string
  enabled: boolean
  push_url: string
  masked_auth_code?: string
}

export interface UpdateNegativeScreenConfig {
  auth_code?: string
  enabled?: boolean
  push_url?: string
}

export interface TestPushRequest {
  task_name?: string
  task_content?: string
  task_result?: string
}

export interface TestPushResponse {
  success: boolean
  task_id?: string
  response_code?: string
  error?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/negative-screen'

/** Get negative screen configuration. */
export function getNegativeScreenConfig() {
  return api.get<ApiResponse<NegativeScreenConfig>>(BASE)
}

/** Update negative screen configuration. */
export function updateNegativeScreenConfig(data: UpdateNegativeScreenConfig) {
  return api.put<ApiResponse<{ user_id: string; masked_auth_code?: string; enabled: boolean }>>(BASE, data)
}

/** Test negative screen push. */
export function testNegativeScreenPush(data: TestPushRequest) {
  return api.post<ApiResponse<TestPushResponse>>(`${BASE}/test`, data)
}

/** Delete negative screen configuration. */
export function deleteNegativeScreenConfig() {
  return api.delete<ApiResponse<{ user_id: string }>>(BASE)
}

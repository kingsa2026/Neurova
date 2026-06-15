import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PoolSettings {
  max_size: number
  ttl_seconds: number
  default_token_budget: number
  model_budgets: Record<string, number>
}

export interface UpdatePoolSettingsRequest {
  max_size?: number
  ttl_seconds?: number
  default_token_budget?: number
}

export interface TestBudgetRequest {
  model_name: string
  capabilities?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/context-pool'

/** Get context pool settings. */
export function getPoolSettings() {
  return api.get<ApiResponse<PoolSettings>>(`${BASE}/pool-settings`)
}

/** Update context pool settings. */
export function updatePoolSettings(data: UpdatePoolSettingsRequest) {
  return api.put<ApiResponse<PoolSettings>>(`${BASE}/pool-settings`, data)
}

/** Get token budget for a specific model. */
export function getModelTokenBudget(modelName: string) {
  return api.get<ApiResponse<{ model_name: string; token_budget: number }>>(`${BASE}/pool-settings/token-budget/${modelName}`)
}

/** Test token budget calculation. */
export function testBudgetCalculation(data: TestBudgetRequest) {
  return api.post<ApiResponse<{ model_name: string; capabilities: string[]; calculated_budget: number; explanation: string }>>(`${BASE}/pool-settings/test-budget`, data)
}

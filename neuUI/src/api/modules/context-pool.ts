import { request } from '@/api'

// ============================================================
// 类型定义
// ============================================================

export interface PoolSettings {
  max_size: number
  ttl_seconds: number
  default_token_budget: number
  model_budgets: Record<string, number>
}

export interface PoolSettingsResponse {
  code: number
  data: PoolSettings
  message?: string
}

export interface UpdatePoolSettingsRequest {
  max_size?: number
  ttl_seconds?: number
  default_token_budget?: number
}

export interface TokenBudgetResponse {
  code: number
  data: {
    model_name: string
    token_budget: number
  }
}

export interface TestBudgetRequest {
  model_name: string
  capabilities?: string[]
}

export interface TestBudgetResponse {
  code: number
  data: {
    model_name: string
    capabilities: string[]
    calculated_budget: number
    explanation: string
  }
}

// ============================================================
// API 方法
// ============================================================

export const contextPoolAPI = {
  /** 获取上下文池设置 */
  getSettings: () =>
    request.get<PoolSettings>('/context/pool-settings'),

  /** 更新上下文池设置 */
  updateSettings: (data: UpdatePoolSettingsRequest) =>
    request.put<PoolSettings>('/context/pool-settings', data),

  /** 获取特定模型的 Token 预算 */
  getTokenBudget: (modelName: string) =>
    request.get<{ model_name: string; token_budget: number }>(
      `/context/pool-settings/token-budget/${encodeURIComponent(modelName)}`
    ),

  /** 测试 Token 预算计算 */
  testBudget: (data: TestBudgetRequest) =>
    request.post<TestBudgetResponse['data']>('/context/pool-settings/test-budget', data),
}

export default contextPoolAPI

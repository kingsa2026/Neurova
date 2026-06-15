import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ModelAdapter {
  id: string
  name: string
  models: string[]
  supports_streaming: boolean
  supports_tools: boolean
  supports_vision: boolean
}

export interface AdapterMatch {
  adapter_id: string
  adapter_name: string
  matched_model: string
}

export interface MatchResult {
  model: string
  matches: AdapterMatch[]
  matched: boolean
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/model-adapter'

/** List all registered model adapters. */
export function getAdapters() {
  return api.get<ApiResponse<{ adapters: ModelAdapter[]; total: number }>>(BASE)
}

/** Get adapter details. */
export function getAdapter(adapterId: string) {
  return api.get<ApiResponse<ModelAdapter>>(`${BASE}/${adapterId}`)
}

/** Check if a model can match a registered adapter. */
export function matchModel(modelName: string) {
  return api.post<ApiResponse<MatchResult>>(`${BASE}/match`, { model: modelName })
}

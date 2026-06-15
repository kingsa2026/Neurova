import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Model {
  id: string
  name: string
  provider_id?: string
  provider?: string
  type?: string
  enabled?: boolean
  tags?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/models'

/** List all models. */
export function listModels() {
  return api.get<Model[] | { models: Model[] }>(BASE)
}

/** Get a single model. */
export function getModel(modelId: string) {
  return api.get<Model>(`${BASE}/${modelId}`)
}

/** Delete a model. */
export function deleteModel(modelId: string) {
  return api.delete<null>(`${BASE}/${modelId}`)
}

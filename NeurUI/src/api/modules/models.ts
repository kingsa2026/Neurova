import api from '@/api'
import type { ModelItem } from '@/types/model'

const BASE = '/models'

export function listModels() {
  return api.get<ModelItem[] | { models: ModelItem[] }>(BASE)
}

export function getModel(modelId: string) {
  return api.get<ModelItem>(`${BASE}/${modelId}`)
}

export function createModel(data: Partial<ModelItem>) {
  return api.post<ModelItem>(BASE, data)
}

export function updateModel(modelId: string, data: Partial<ModelItem>) {
  return api.put<ModelItem>(`${BASE}/${modelId}`, data)
}

export function deleteModel(modelId: string) {
  return api.delete<null>(`${BASE}/${modelId}`)
}

export function setActiveModel(data: { provider_id: string; model_id: string }) {
  return api.post(`${BASE}/active`, data)
}

export function getActiveModel() {
  return api.get<ModelItem>(`${BASE}/active`)
}

export function fetchModelsFromProvider(providerId: string) {
  return api.get<ModelItem[]>(`${BASE}/fetch`, { params: { provider_id: providerId } })
}

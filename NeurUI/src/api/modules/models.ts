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

// ---------------------------------------------------------------------------
// 模型能力自动检测与按能力查询（2026-09-03）
// 六类核心能力: text/reasoning/vision/video/image_generation/video_generation
// ---------------------------------------------------------------------------

/** 批量自动检测模型能力并持久化到服务商元数据。 */
export function detectCapabilities(data: { provider_id?: string; model_id?: string; force?: boolean }) {
  return api.post<{ code: number; message: string; data: { detected: number; results: Array<{ provider_id: string; model_id: string; capabilities: string[] }> } }>(
    `${BASE}/detect-capabilities`,
    data,
  )
}

/** 按能力过滤模型列表（AIGC 页面下拉数据源）。 */
export function listModelsByCapability(capability: string) {
  return api.get<ModelItem[]>(`${BASE}/by-capability`, { params: { cap: capability } })
}

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
// 模型级连接测试 + 多模态真实探测（QwenPaw 对齐）
// ---------------------------------------------------------------------------

export interface ModelConnectionResult {
  model_id: string
  connected: boolean
  message: string
  /** 可用性七态:available/permission_denied/model_not_found/incompatible_api/rate_limited/transient_error/unverified */
  status?: string
  http_status?: number | null
  retryable?: boolean | null
  checked_at?: string | null
  verification?: 'live' | 'provider_only' | 'unverified' | null
  error_category?: string | null
  error_hint?: string
}

/** 模型级连接测试（真实 chat ping,非仅本地构造实例）。 */
export function checkModelConnection(modelId: string) {
  return api.post<{ code: number; data: ModelConnectionResult }>(`${BASE}/check-connection`, null, {
    params: { model_id: modelId },
  })
}

/** 多模态真实探测（32x32 红色 PNG 图像问答,语义校验答案）。 */
export function probeModelMultimodal(data: { model_id: string; force?: boolean }) {
  return api.post<{ code: number; data: { model_id: string; result: Record<string, unknown> } }>(
    `${BASE}/probe-multimodal`,
    data,
  )
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

// ==================== 模型下载（双源选择 + 后台触发 + 进度轮询） ====================

export type DownloadChoice = 'auto' | 'always_modelscope' | 'always_huggingface' | 'skip'

export interface PendingDownloadItem {
  model: string
  description: string
  size_hint: string
  available: boolean
  has_ms_mirror: boolean
  choice: DownloadChoice
}

export interface DownloadState {
  model: string
  status: 'pending' | 'downloading' | 'done' | 'failed' | 'skipped'
  error: string
  percentage: number
}

export function listPendingDownloads() {
  return api.get<PendingDownloadItem[]>(`${BASE}/pending-downloads`)
}

export function getDownloadSource() {
  return api.get<Record<string, DownloadChoice>>(`${BASE}/download-source`)
}

export function setDownloadSource(data: { model: string; choice: DownloadChoice }) {
  return api.post<{ ok: boolean }>(`${BASE}/download-source`, data)
}

export function triggerDownload(data: { model: string; source?: string }) {
  return api.post<DownloadState>(`${BASE}/download`, data)
}

export function getDownloadProgress() {
  return api.get<DownloadState[]>(`${BASE}/download-progress`)
}

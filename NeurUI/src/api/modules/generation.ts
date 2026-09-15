import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types（批次2：与 neurova/api/endpoints/generation.py 实测契约逐字段对齐）
// ---------------------------------------------------------------------------

export interface TextGenerationPayload {
  prompt: string
  model?: string
  temperature?: number
  max_tokens?: number
  session_id?: string
}

/** 后端 /generation/text 实返：{text, model, routed, routed_model?, routed_provider?, request_id} */
export interface TextGenerationResult {
  text: string
  model: string
  routed: boolean
  routed_model?: string | null
  routed_provider?: string | null
  request_id: string
}

/** 后端 ImageGenerationRequest：无 style 字段（旧实现的 style 被静默丢弃，已删）。
 * seed/strength 走 R2 能力自适应路由：支持则透传，不支持进 ignored_params 显式标注。 */
export interface ImageGenerationPayload {
  prompt: string
  model?: string
  width?: number
  height?: number
  num_images?: number
  protocol?: string
  provider_id?: string
  api_key?: string
  base_url?: string
  ref_images?: string[]
  negative_prompt?: string
  seed?: number
  strength?: number
}

export interface ImageGenerationResult {
  images: Array<{ url: string; path?: string; error?: string }>
  task_id: string
  /** 服务商不支持而被显式忽略的参数（csv），如 "seed,strength" */
  ignored_params?: string
}

/** 音色条目（GET /generation/voices，引擎真实列表）。 */
export interface VoiceOption {
  id: string
  label: string
  gender?: string
  locale?: string
}

export interface AudioGenerationPayload {
  text: string
  model?: string
  voice?: string
  speed?: number
}

/** 批次1 起音频统一 JSON 契约（产物落盘 + url），不再是裸二进制。 */
export interface AudioGenerationResult {
  url: string
  path: string
  task_id: string
  request_id?: string
}

export interface VideoGenerationPayload {
  prompt: string
  model?: string
  duration?: number
  resolution?: string
  protocol?: string
  provider_id?: string
  api_key?: string
  base_url?: string
  ref_images?: string[]
  audio?: boolean
}

export type TaskKind = 'image' | 'video' | 'audio'
export type TaskStatus = 'submitted' | 'running' | 'succeeded' | 'failed'

export interface GenerationTask {
  task_id: string
  kind: TaskKind
  protocol: string
  model: string
  status: TaskStatus
  prompt: string
  submitted_at: number
  updated_at?: number
  local_path: string
  url: string
  source: string
  error: string
  /** R2：服务商不支持而被显式忽略的参数（csv） */
  ignored_params?: string
  /** C3：保留清理已删文件（账本行保留）——url 恒空，UI 显示「已过期」 */
  file_missing?: boolean
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/generation'

/** 文本生成（model=auto/缺省 → 后端 LLMRouter 自动路由）。 */
export function generateText(data: TextGenerationPayload) {
  return api.post<ApiResponse<TextGenerationResult>>(`${BASE}/text`, data)
}

/** 图像生成（同步返回本地化产物 + task_id；成败均落任务账本）。 */
export function generateImage(data: ImageGenerationPayload) {
  return api.post<ApiResponse<ImageGenerationResult>>(`${BASE}/image`, data)
}

/** 音频生成（TTS，JSON 契约：url/path/task_id）。 */
export function generateAudio(data: AudioGenerationPayload) {
  return api.post<ApiResponse<AudioGenerationResult>>(`${BASE}/audio`, data)
}

/** R2：可用音色列表（引擎真实枚举；引擎不可用时为空数组，非硬编码假列表）。 */
export function listGenerationVoices() {
  return api.get<ApiResponse<{ voices: VoiceOption[] }>>(`${BASE}/voices`)
}

/** 视频任务提交（异步，返回 task_id 供轮询）。 */
export function submitVideo(data: VideoGenerationPayload) {
  return api.post<ApiResponse<{ task_id: string; status: TaskStatus; protocol: string }>>(
    `${BASE}/video`, data)
}

/** 视频任务轮询（账本 + 远程协议收口）。 */
export function getVideoTaskStatus(taskId: string) {
  return api.get<ApiResponse<{
    task_id: string
    status: TaskStatus
    url?: string
    error?: string
    warning?: string
  }>>(`${BASE}/video/status/${taskId}`)
}

/**
 * 2026-09-15 自适应推导查询：选定模型后查询将生效的服务商/协议做只读展示。
 * 与提交路径同源（后端 derive_generation_protocol 单源），前端不重复矩阵规则。
 */
export interface GenerationProtocolInfo {
  kind: string
  model: string
  provider_id: string
  protocol: string
}
export function resolveGeneration(kind: 'image' | 'video', model: string, providerId?: string) {
  return api.get<ApiResponse<GenerationProtocolInfo>>(`${BASE}/resolve`, {
    params: { kind, model, provider_id: providerId || '' },
  })
}

/** 生成任务历史（账本快照，可按 kind/status 过滤；仅本人任务）。 */
export function listGenerationTasks(params?: { kind?: TaskKind; status?: TaskStatus }) {
  return api.get<ApiResponse<{ tasks: GenerationTask[] }>>(`${BASE}/tasks`, { params })
}

/** L4：AIGC 生成用量聚合（近 N 天按天/类型/状态）。 */
export interface AigcUsageRow {
  kind: string
  status: string
  items: number
  calls: number
  duration_ms: number
  usage_date?: string
}

export interface AigcUsageSummary {
  daily: AigcUsageRow[]
  totals: AigcUsageRow[]
  days: number
}

export function getGenerationUsage(days = 30) {
  return api.get<ApiResponse<AigcUsageSummary>>(`${BASE}/usage`, { params: { days } })
}

// ---------------------------------------------------------------------------
// Model / Provider types
// ---------------------------------------------------------------------------

export interface ModelItem {
  id: string
  name: string
  provider_id: string
  type: 'text' | 'image' | 'audio'
  tags: string[]          // 'free', 'built-in', 'user-added'
  enabled: boolean
  capabilities: string[]  // 六类核心: text/reasoning/vision/video/image_generation/video_generation（另有 audio/tts/stt/tool_use）
  is_active: boolean
  context_window?: number
  max_tokens?: number
  pricing?: { input: number; output: number }
  owned_by?: string
}

export interface Provider {
  id: string
  name: string
  icon: string            // emoji or short text
  iconSrc?: string        // image URL for logo icons
  color: string           // icon background color
  type: 'builtin' | 'custom'
  category: 'paid' | 'free' | 'local'
  status: 'available' | 'unavailable' | 'not_configured' | 'not_ready'
  statusLabel: string
  base_url: string
  api_key?: string
  api_key_configured: boolean
  auth_method?: 'api_key' | 'bearer'
  protocol: 'openai' | 'anthropic'
  models: ModelItem[]
  model_count: number
  enabled: boolean
  health: 'healthy' | 'unhealthy' | 'unknown'
  priority: number
  description?: string
  config?: Record<string, unknown>
  headers?: Record<string, string>
  gen_params?: Record<string, unknown>
}

/**
 * 将后端 GET /models 返回的 ModelInfo（{model_id, name, provider, capabilities, ...}）
 * 归一化为前端 ModelItem 形状（{id, name, provider_id, ...}）。
 *
 * 后端字段与前端类型不一致：model_id -> id、provider -> provider_id，
 * 且后端无 enabled/tags/type 等字段，需在此补齐默认值，避免各处读取 m.provider_id / m.id 时得到 undefined。
 */
export function normalizeModel(item: Record<string, any>): ModelItem {
  const provider = item.provider ?? item.provider_id ?? ''
  return {
    id: item.model_id ?? item.id ?? item.name ?? 'unknown',
    name: item.name ?? item.model_id ?? item.id ?? 'Unknown',
    provider_id: provider,
    type: item.type === 'image' || item.type === 'audio' ? item.type : 'text',
    tags: Array.isArray(item.tags) ? item.tags : [],
    enabled: item.enabled ?? true,
    capabilities: Array.isArray(item.capabilities) ? item.capabilities : [],
    is_active: item.is_active ?? false,
    context_window: item.context_window,
    max_tokens: item.max_tokens,
    pricing: item.pricing,
    owned_by: item.owned_by ?? provider,
  }
}

export interface DefaultLLMConfig {
  provider_id: string
  model_id: string
}

export interface GenerationParams {
  temperature: number
  max_tokens: number
  stream_mode: boolean
}

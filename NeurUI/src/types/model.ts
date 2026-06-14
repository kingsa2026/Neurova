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
  capabilities: string[]  // 'text', 'vision', 'audio', 'tool_use', etc.
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

export interface DefaultLLMConfig {
  provider_id: string
  model_id: string
}

export interface GenerationParams {
  temperature: number
  max_tokens: number
  stream_mode: boolean
}

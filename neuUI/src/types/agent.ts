// ==================== Agent 管理相关类型 ====================

export interface TTSConfig {
  enabled: boolean
  model?: string
  voiceType?: 'male' | 'female' | 'custom'
  speed?: number
  pitch?: number
}

export interface Agent {
  id: string
  agentId: string
  name: string
  description?: string
  workingDirectory?: string
  llmModel?: string
  llmProvider?: string
  personality?: string
  constitution?: string
  ttsConfig?: TTSConfig
  // 扁平化的 TTS 配置字段（与后端API返回一致）
  tts_enabled?: boolean
  tts_voice?: string
  tts_speed?: number
  tts_pitch?: number
  status?: 'active' | 'inactive' | 'error'
  memoryCount?: number
  skillCount?: number
  createdAt?: string
  updatedAt?: string
}

export interface AgentCreateRequest {
  agent_id: string
  name: string
  description?: string
  workspace_path?: string
  llm_model?: string
  llm_provider?: string
  personality?: string
  constitution?: string
  enable_memory?: boolean
  // TTS 配置
  tts_enabled?: boolean
  tts_voice?: string
  tts_speed?: number
  tts_pitch?: number
}

export interface AgentUpdateRequest {
  agent_id?: string
  name?: string
  description?: string
  llm_model?: string
  llm_provider?: string
  personality?: string
  constitution?: string
  workspace_path?: string
  enable_memory?: boolean
  // TTS 配置
  tts_enabled?: boolean
  tts_voice?: string
  tts_speed?: number
  tts_pitch?: number
}

export type AgentListResponse = Agent[]
export type AgentResponse = Agent

export interface Agent {
  id: string
  name: string
  description?: string
  model?: string
  provider?: string
  status: 'active' | 'inactive' | 'sleeping' | 'error'
  avatar?: string
  /** 人设提示词（后端 agent_config.json 的 system_prompt） */
  system_prompt?: string
  /** Agent 角色（如 assistant/researcher，用于蜂群派生时挑选执行者） */
  role?: string
  createdAt: string
  updatedAt: string
  config?: AgentConfig
  stats?: AgentStats
}

export interface AgentConfig {
  systemPrompt?: string
  temperature?: number
  maxTokens?: number
  topP?: number
  ttsEnabled?: boolean
  ttsVoice?: string
  ttsSpeed?: number
  ttsPitch?: number
  tools?: string[]
  skills?: string[]
}

export interface AgentStats {
  totalConversations: number
  totalMessages: number
  totalTokens: number
  avgResponseTime: number
  lastActiveAt?: string
}

export interface ApiResponse<T = unknown> {
  code: number
  success: boolean
  message: string
  data: T
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

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
  /** 所属分组（后端 group_id；编辑态回显用，缺省串 = 未绑定） */
  group_id?: string
  /** 性格设定（后端 AgentConfig.personality，表单编辑态回显） */
  personality?: string
  /** 行为准则/宪法（后端 AgentConfig.constitution，表单编辑态回显） */
  constitution?: string
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

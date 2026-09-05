import { request } from '@/api'

export interface AgentInfo {
  agent_id: string
  name: string
  description: string
  workspace_path: string
  llm_model: string
  llm_provider?: string
  personality?: string
  constitution?: string
  memory_db_path?: string
  memory_enabled: boolean
  status: 'running' | 'stopped' | 'error'
  created_at: string
  updated_at: string
  is_default?: boolean
}

export interface AgentStats {
  agent_id: string
  memory: {
    total_memories: number
    categories: Record<string, number>
  }
  llm: {
    total_calls: number
    total_tokens: number
  }
  conversation_history_length: number
}

export interface PersonalityTraits {
  openness?: number
  conscientiousness?: number
  extraversion?: number
  agreeableness?: number
  neuroticism?: number
}

export interface AgentPersonality {
  agent_id: string
  traits: PersonalityTraits
  values: Record<string, string>
  goals: string[]
  interests: string[]
  communication_style: string
  preview: string
}

export interface AgentConstitution {
  agent_id: string
  constitution: string
  version: string
  updated_at: string
  preview: string
}

export interface AgentConfig {
  agent_id: string
  name: string
  description: string
  workspace_path: string
  llm_model: string
  llm_provider: string
  personality: string
  constitution: string
  memory_db_path: string
  enable_memory: boolean
  enable_streaming: boolean
  llm_temperature: number
  max_tokens: number
  show_thinking: boolean
  show_tool_messages: boolean
  created_at: string
  updated_at: string
}

export interface SwitchResponse {
  old_default: string
  new_default: string
}

export interface UpdatePersonalityRequest {
  traits?: PersonalityTraits
  values?: Record<string, string>
  goals?: string[]
  interests?: string[]
  communication_style?: string
}

export interface UpdateConstitutionRequest {
  constitution: string
  version?: string
}

export interface UpdateConfigRequest {
  personality?: string
  constitution?: string
  llm_provider?: string
  llm_model?: string
  memory_db_path?: string
  enable_memory?: boolean
  llm_temperature?: number
  max_tokens?: number
  show_thinking?: boolean
  show_tool_messages?: boolean
}

export const agentAPI = {
  list: () => request.get<{count: number, agents: AgentInfo[], default_agent_id: string, user_role: string}>('/agents'),
  
  get: (id: string) => request.get<AgentInfo>(`/agents/${id}`),
  
  create: (data: Partial<AgentInfo>) => request.post('/agents', data),
  
  update: (id: string, data: Partial<AgentInfo>) => request.put(`/agents/${id}/config`, data),
  
  delete: (id: string) => request.delete(`/agents/${id}`),
  
  getStats: (id: string) => request.get<AgentStats>(`/agents/${id}/stats`),
  
  switch: (id: string) => request.post<SwitchResponse>(`/agents/${id}/switch`),
  
  getHealth: (id: string) => request.get<{status: string, uptime: number, memory_usage: number}>(`/agents/${id}/health`),
  
  restart: (id: string) => request.post<{success: boolean, message: string}>(`/agents/${id}/restart`),
  
  getStatus: (id: string) => request.get<{agent_id: string, status: string, is_default: boolean}>(`/agents/${id}/status`),
  
  getCapabilities: (id: string) => request.get<{agent_id: string, capabilities: string[], features: Record<string, boolean>}>(`/agents/${id}/capabilities`),
  
  getConstitution: (id: string) => request.get<AgentConstitution>(`/agents/${id}/constitution`),
  
  updateConstitution: (id: string, data: UpdateConstitutionRequest) => 
    request.put<{agent_id: string, old_version: string, new_version: string, version: string}>(`/agents/${id}/constitution`, data),
  
  getPersonality: (id: string) => request.get<AgentPersonality>(`/agents/${id}/personality`),
  
  updatePersonality: (id: string, data: UpdatePersonalityRequest) => 
    request.put<AgentPersonality>(`/agents/${id}/personality`, data),
  
  getConfig: (id: string) => request.get<AgentConfig>(`/agents/${id}/config`),
  
  updateConfig: (id: string, data: UpdateConfigRequest) => 
    request.put<AgentConfig>(`/agents/${id}/config`, data),
}

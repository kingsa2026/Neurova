/** 管理面 API（模型/记忆/技能/智能体，对齐 Web 端契约） */
import { apiGet, apiPost } from '@/utils/http'

export interface ModelInfo {
  id: string
  name?: string
  provider?: string
  enabled?: boolean
  is_default?: boolean
  [key: string]: unknown
}

export interface MemoryItem {
  id?: string
  memory_id?: string
  content?: string
  keyword?: string
  score?: number
  created_at?: string
  [key: string]: unknown
}

export interface MemoryStats {
  total?: number
  [key: string]: unknown
}

export interface SkillInfo {
  skill_id?: string
  id?: string
  name?: string
  description?: string
  enabled?: boolean
  [key: string]: unknown
}

export interface AgentInfo {
  agent_id: string
  name?: string
  status?: string
  model?: string
  provider?: string
  description?: string
  [key: string]: unknown
}

export async function listModels(): Promise<ModelInfo[]> {
  const rows = await apiGet<ModelInfo[] | { models?: ModelInfo[] }>('/models')
  if (Array.isArray(rows)) return rows
  return rows?.models ?? []
}

export async function searchMemories(keyword: string): Promise<MemoryItem[]> {
  const rows = await apiGet<MemoryItem[] | { memories?: MemoryItem[]; results?: MemoryItem[] }>(
    '/memory',
    keyword ? { keyword } : undefined,
  )
  if (Array.isArray(rows)) return rows
  return rows?.memories ?? rows?.results ?? []
}

export async function memoryStats(): Promise<MemoryStats> {
  return apiGet<MemoryStats>('/memory/stats')
}

export async function listSkills(): Promise<SkillInfo[]> {
  const rows = await apiGet<SkillInfo[] | { skills?: SkillInfo[] }>('/skills')
  if (Array.isArray(rows)) return rows
  return rows?.skills ?? []
}

export async function listAgents(): Promise<AgentInfo[]> {
  const rows = await apiGet<AgentInfo[] | { agents?: AgentInfo[] }>('/agents')
  if (Array.isArray(rows)) return rows
  return rows?.agents ?? []
}

export async function switchAgent(agentId: string): Promise<void> {
  await apiPost(`/agents/${encodeURIComponent(agentId)}/switch`)
}

export interface KnowledgeEntry {
  knowledge_id?: string
  title?: string
  content?: string
  [key: string]: unknown
}

export async function listKnowledge(): Promise<KnowledgeEntry[]> {
  const rows = await apiGet<KnowledgeEntry[] | { items?: KnowledgeEntry[] }>('/knowledge')
  if (Array.isArray(rows)) return rows
  return rows?.items ?? []
}

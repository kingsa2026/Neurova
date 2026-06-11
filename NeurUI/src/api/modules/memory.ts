import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MemoryEntry {
  id: string
  agent_id: string
  content: string
  type: 'short_term' | 'long_term' | 'episodic' | 'semantic'
  importance: number
  tags?: string[]
  metadata?: Record<string, unknown>
  created_at: string
  expires_at?: string
}

export interface MemoryCreatePayload {
  agent_id: string
  content: string
  type?: string
  importance?: number
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface MemorySearchResult {
  id: string
  content: string
  score: number
  type: string
  created_at: string
  channel_scores?: Record<string, number>  // NeRF 体渲染各通道贡献
}

export interface MemoryStats {
  total_memories: number
  by_type: { type: string; count: number }[]
  avg_importance: number
  storage_used: number
}

// NeRF 体渲染融合配置
export interface NerfSettings {
  fusion_mode: 'legacy' | 'nerf'
  density_scale: number
  channel_densities: Record<string, number>
  available_modes: string[]
  mode_descriptions: Record<string, string>
}

export interface NerfSettingsUpdate {
  fusion_mode?: 'legacy' | 'nerf'
  density_scale?: number
  channel_densities?: Record<string, number>
}

export interface ChannelWeights {
  intent: string
  weights: Record<string, number>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/memory'

/** List memories for an agent. */
export function getMemories(agentId: string, params?: PageParams & { type?: string; min_importance?: number }) {
  return api.get<ApiResponse<PaginatedData<MemoryEntry>>>(BASE, { params: { ...params, agent_id: agentId } })
}

/** Get a single memory. */
export function getMemory(id: string) {
  return api.get<ApiResponse<MemoryEntry>>(`${BASE}/${id}`)
}

/** Create a memory. */
export function createMemory(data: MemoryCreatePayload) {
  return api.post<ApiResponse<MemoryEntry>>(BASE, data)
}

/** Update a memory. */
export function updateMemory(id: string, data: Partial<MemoryCreatePayload>) {
  return api.put<ApiResponse<MemoryEntry>>(`${BASE}/${id}`, data)
}

/** Delete a memory. */
export function deleteMemory(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Search memories with semantic similarity. */
export function searchMemories(agentId: string, query: string, params?: { limit?: number; type?: string }) {
  return api.post<ApiResponse<MemorySearchResult[]>>(`${BASE}/search`, { agent_id: agentId, query, ...params })
}

/** Get memory statistics. */
export function getMemoryStats(agentId: string) {
  return api.get<ApiResponse<MemoryStats>>(`${BASE}/stats`, { params: { agent_id: agentId } })
}

// ---------------------------------------------------------------------------
// NeRF Settings API
// ---------------------------------------------------------------------------

const ENHANCED_BASE = '/enhanced-memory-search'

/** Get NeRF volume rendering settings. */
export function getNerfSettings() {
  return api.get<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings`)
}

/** Update NeRF volume rendering settings. */
export function updateNerfSettings(data: NerfSettingsUpdate) {
  return api.put<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings`, data)
}

/** Reset NeRF settings to defaults. */
export function resetNerfSettings() {
  return api.post<ApiResponse<NerfSettings>>(`${ENHANCED_BASE}/nerf-settings/reset`)
}

/** Get channel weights for a specific intent. */
export function getChannelWeights(intent: string) {
  return api.get<ApiResponse<ChannelWeights>>(`${ENHANCED_BASE}/channel-weights`, { params: { intent } })
}

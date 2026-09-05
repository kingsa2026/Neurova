import { request } from '@/api'

export interface MemoryItem {
  id: string
  content: string
  type: string
  importance: number
  created_at: string
  updated_at: string
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface MemoryStats {
  total_memories: number
  categories: Record<string, number>
  importance_distribution: Record<string, number>
}

export interface MemoryCategory {
  id: string
  name: string
  count: number
  icon: string
}

export interface ForgetRequest {
  reason?: string
}

export interface StrengthenRequest {
  strength: number
}

export interface BatchOperationRequest {
  operation: 'delete' | 'strengthen' | 'forget' | 'categorize'
  memory_ids: string[]
  category?: string
  strength?: number
}

export interface BatchOperationResult {
  operation: string
  total: number
  succeeded: number
  failed: number
  failed_ids: string[]
}

export interface ExportMemoriesRequest {
  format?: 'json' | 'csv'
  category?: string
  since?: string
  until?: string
}

export interface ImportMemoriesRequest {
  memories: Partial<MemoryItem>[]
  overwrite?: boolean
}

export const memoryAPI = {
  list: (agentId?: string) => request.get<{memories: MemoryItem[], total: number}>('/memories', { params: { agent_id: agentId } }),
  
  create: (data: Partial<MemoryItem>, agentId?: string) => 
    request.post<MemoryItem>('/memories', data, { params: { agent_id: agentId } }),
  
  get: (id: string) => request.get<MemoryItem>(`/memories/${id}`),
  
  delete: (id: string) => request.delete(`/memories/${id}`),
  
  getStats: (agentId?: string) => request.get<MemoryStats>('/memories/stats', { params: { agent_id: agentId } }),
  
  forget: (id: string, data?: ForgetRequest) => 
    request.post<{memory_id: string, success: boolean, forgotten: boolean}>(`/memories/${id}/forget`, data),
  
  strengthen: (id: string, data: StrengthenRequest) => 
    request.post<{memory_id: string, success: boolean, strength: number, strengthened: boolean}>(`/memories/${id}/strengthen`, data),
  
  getCategories: (agentId?: string) => 
    request.get<{categories: MemoryCategory[], total: number}>('/memories/categories', { params: { agent_id: agentId } }),
  
  batch: (data: BatchOperationRequest) => request.post<BatchOperationResult>('/memories/batch', data),
  
  export: (params?: ExportMemoriesRequest) => 
    request.get<{format: string, count: number, memories: MemoryItem[], exported_at: string}>('/memories/export', { params }),
  
  import: (data: ImportMemoriesRequest) => 
    request.post<{total: number, succeeded: number, failed: number, failed_items: Record<string, unknown>[]}>(`/memories/import`, data),
}

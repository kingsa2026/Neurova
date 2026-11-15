/** 其余移动端接口的薄封装（对齐 NeurUI api modules 的后端契约） */
import { apiGet, apiPost, http } from '@/utils/http'

export interface AgentItem {
  agent_id: string
  name: string
  description?: string
}

export async function listAgents(): Promise<AgentItem[]> {
  const rows = await apiGet<AgentItem[] | { agents?: AgentItem[] }>('/agents')
  if (Array.isArray(rows)) return rows
  return rows?.agents ?? []
}

export interface NotificationItem {
  id: string
  title?: string
  content?: string
  message?: string
  created_at?: string
  read?: boolean
}

export async function listNotifications(): Promise<NotificationItem[]> {
  const rows = await apiGet<NotificationItem[] | { notifications?: NotificationItem[] }>('/notifications')
  if (Array.isArray(rows)) return rows
  return rows?.notifications ?? []
}

export async function unreadNotificationCount(): Promise<number> {
  const v = await apiGet<number | { count?: number }>('/notifications/unread-count')
  if (typeof v === 'number') return v
  return v?.count ?? 0
}

export async function markNotificationRead(id: string): Promise<void> {
  await apiPost(`/notifications/${encodeURIComponent(id)}/read`)
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiPost('/notifications/mark-all-read')
}

export interface FileUploadResult {
  file_id?: string
  name?: string
  size?: number
}

/** multipart 上传（对齐 files_api.upload_file：file 二进制 + query agent_id/session_id） */
export async function uploadFile(
  file: File,
  agentId = 'default',
  sessionId = 'default',
): Promise<FileUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const r = await http.post('/files/upload', form, {
    params: { agent_id: agentId, session_id: sessionId },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return (r?.data?.data ?? r?.data) as FileUploadResult
}

export interface KnowledgeHit {
  knowledge_id?: string
  title?: string
  content?: string
  score?: number
  source?: string
}

export async function searchKnowledge(query: string, topK = 8): Promise<KnowledgeHit[]> {
  const rows = await apiPost<KnowledgeHit[] | { results?: KnowledgeHit[] }>('/knowledge/search', {
    query,
    top_k: topK,
  })
  if (Array.isArray(rows)) return rows
  return rows?.results ?? []
}

export interface TaskBoard {
  id?: string
  name?: string
  tasks?: Array<Record<string, unknown>>
}

export async function listTaskBoards(): Promise<TaskBoard[]> {
  const rows = await apiGet<TaskBoard[] | { boards?: TaskBoard[] }>('/tasks/boards')
  if (Array.isArray(rows)) return rows
  return rows?.boards ?? []
}

export interface FileItem {
  file_id?: string
  name?: string
  size?: number
  uploaded_at?: string
}

export async function listFiles(agentId?: string): Promise<FileItem[]> {
  const rows = await apiGet<FileItem[] | { files?: FileItem[] }>('/files', agentId ? { agent_id: agentId } : undefined)
  if (Array.isArray(rows)) return rows
  return rows?.files ?? []
}

export async function checkHealth(): Promise<boolean> {
  try {
    const servers = (await import('@/stores/servers')).useServersStore()
    const r = await fetch(`${servers.apiBase.replace('/api/v1', '')}/api/v1/health`)
    return r.ok
  } catch {
    return false
  }
}

export { http }

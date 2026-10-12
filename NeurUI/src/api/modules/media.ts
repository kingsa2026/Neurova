/**
 * Media storage API — 与后端 neurova/api/endpoints/media.py 一一对应的契约层。
 *
 * F-1 契约对齐（台账）：
 * - listMedia → GET /media/list（offset/limit 分页 + search 服务端过滤；响应
 *   data.media/total/offset/limit）；
 * - getMediaInfo → GET /media/{id}/metadata（原 /{id}/info 404）；
 * - downloadMedia → GET /media/download/{id}（原 /{id}/download 404）；
 * - batchDeleteMedia → POST /media/batch-delete，body { media_ids }（原 /batch-delete 404）；
 * - saveMedia 必须携带后端必填的 media_type 表单字段（缺省 422）；
 * - getMediaStats 移除：后端无 /stats?agent_id= 查询参数版本（仅 /stats/{agent_id}
 *   路径版本），且 UI 无统计展示；
 * - 字段对齐后端 save_media 返回的 media_info：media_id/filename/media_type/mime_type/size/created_at
 *   （epoch 秒），无 url/tags。
 */
import api, { request } from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — 与后端 save_media 返回的 media_info 字段对齐
// ---------------------------------------------------------------------------

export interface MediaItem {
  media_id: string
  filename: string
  media_type: string
  mime_type: string
  size: number
  agent_id?: string
  user_id?: string | null
  memory_id?: string | null
  storage_path: string
  /** epoch 秒（后端 time.time()） */
  created_at: number
  metadata?: Record<string, unknown>
  /** 回收站标记（§6-158）：现役读面不会带出 is_deleted 为真的行，只有 /trash 会。 */
  is_deleted?: boolean
  deleted_at?: number
}

export interface MediaListResult {
  media: MediaItem[]
  total: number
  offset: number
  limit: number
}

export interface BatchDeleteResult {
  succeeded: string[]
  failed: { media_id: string; reason: string }[]
}

export interface MediaConfig {
  max_file_size: number
  allowed_types: string[]
  storage_path: string
  enable_compression: boolean
  created_at: number
  updated_at: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/media'

/** 与后端 `DELETE_MODES` 同一份口径：`trash` 留字节、`permanent` 连字节一起删。 */
export type MediaDeleteMode = 'trash' | 'permanent'

/** 由文件 MIME 推导后端 allowed_types 中的媒体类型（save 必填字段）。 */
function mediaTypeFromFile(file: File): string {
  const mime = file.type || ''
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('audio/')) return 'audio'
  if (mime.startsWith('video/')) return 'video'
  return 'file'
}

/** Upload/save a media file (multipart; media_type 由 MIME 推导，后端必填). */
export function saveMedia(file: File, agentId?: string, metadata?: Record<string, unknown>) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('media_type', mediaTypeFromFile(file))
  if (agentId) formData.append('agent_id', agentId)
  if (metadata) formData.append('metadata', JSON.stringify(metadata))
  return api.post<ApiResponse<MediaItem>>(`${BASE}/save`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** Get a media file content (binary blob). */
export function getMedia(id: string) {
  return request.get(`${BASE}/${id}`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** List media files (offset/limit 分页；search 走服务端过滤 filename/media_id；响应 data.media/total/offset/limit). */
export function listMedia(params?: {
  offset?: number
  limit?: number
  agent_id?: string
  media_type?: string
  search?: string
}) {
  return api.get<ApiResponse<MediaListResult>>(`${BASE}/list`, { params })
}

/** Get media metadata (no binary). */
export function getMediaInfo(id: string) {
  return api.get<ApiResponse<MediaItem>>(`${BASE}/${id}/metadata`)
}

/** Download a media file as blob (Content-Disposition attachment). */
export function downloadMedia(id: string) {
  return request.get(`${BASE}/download/${id}`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** Delete a media file. 缺省 `permanent` —— 后端默认档就是硬删，前端不把语义翻成软删。 */
export function deleteMedia(id: string, mode: MediaDeleteMode = 'permanent') {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}?mode=${mode}`)
}

/** 移入回收站 = `deleteMedia(id, 'trash')` 的具名写法：调用点读起来就是它做的事。 */
export function moveToTrash(id: string) {
  return deleteMedia(id, 'trash')
}

/** 回收站读面（§6-158）：软删条目从这里读回，响应形状与 /list 同一份（media/total/offset/limit）。 */
export function listTrash(params?: {
  offset?: number
  limit?: number
  agent_id?: string
}) {
  return api.get<ApiResponse<MediaListResult>>(`${BASE}/trash`, { params })
}

/** 从回收站恢复；字节已不在盘上时后端诚实回 410，不造「活但取不到」的记录。 */
export function restoreMedia(id: string) {
  return api.post<ApiResponse<{ media_id: string }>>(`${BASE}/${id}/restore`)
}

/** Batch delete media files; 每个 ID 独立回报 succeeded/failed. 缺省同样是 permanent. */
export function batchDeleteMedia(ids: string[], mode: MediaDeleteMode = 'permanent') {
  return api.post<ApiResponse<BatchDeleteResult>>(`${BASE}/batch-delete`, { media_ids: ids, mode })
}

/** Get media storage configuration. */
export function getMediaConfig() {
  return api.get<ApiResponse<MediaConfig>>(`${BASE}/config`)
}

/** Update media storage configuration. */
export function updateMediaConfig(
  data: Partial<Pick<MediaConfig, 'max_file_size' | 'allowed_types' | 'storage_path' | 'enable_compression'>>,
) {
  return api.put<ApiResponse<MediaConfig>>(`${BASE}/config`, data)
}

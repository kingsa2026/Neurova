import api from '@/api'
import { request } from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileItem {
  id: string
  name: string
  type?: string
  size?: number
  // 后端 version 是字符串（如 '1.0.0'）
  version?: string | number
  status?: string
  url?: string
  agent_id?: string
  // 后端 FileInfo.created_at 是 epoch 秒（float）
  created_at: number
  // 后端 FileInfo 实测契约（批次3：上传返回绝对落盘 path，供 AIGC 参考图引用）
  file_id?: string
  filename?: string
  path?: string
}

export interface FileVersion {
  version: number
  size?: number
  created_at: string
}

export interface FileListParams {
  page?: number
  page_size?: number
  agent_id?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/files'

/**
 * 后端 `GET /files` 回**裸** `List[FileInfo]`（files_api.py，无信封无分页），
 * 键名是 `file_id/filename/file_type`，与前端 FileItem 的 `id/name/type` 不同名。
 * 在模块边界归一成 FileItem[]（与 extractUploadedFileId 同一契约），页面不再
 * 各自猜键名——FilePage 原按 `{data:{items}}` 信封读 `res?.data` 恒 undefined，
 * 列表恒空（P1-22 同根因命中点，审计 2026-11-16）。
 */
export function normalizeFileInfoList(raw: unknown): FileItem[] {
  const body =
    raw && typeof raw === 'object' && 'data' in raw ? (raw as { data?: unknown }).data ?? raw : raw
  const rows = Array.isArray(body)
    ? body
    : Array.isArray((body as { items?: unknown[] })?.items)
      ? (body as { items: unknown[] }).items
      : []
  return rows
    .map((row) => {
      const r = (row ?? {}) as Record<string, unknown>
      return {
        id: String(r.file_id ?? r.id ?? ''),
        name: String(r.filename ?? r.name ?? ''),
        type: (r.file_type ?? r.type) as string | undefined,
        size: (r.size as number | undefined) ?? undefined,
        version: (r.version as string | number | undefined) ?? undefined,
        status: (r.status as string | undefined) ?? undefined,
        agent_id: (r.agent_id as string | undefined) ?? undefined,
        created_at: r.created_at as number,
        file_id: (r.file_id as string | undefined) ?? undefined,
        filename: (r.filename as string | undefined) ?? undefined,
        path: (r.path as string | undefined) ?? undefined,
      }
    })
    .filter((f) => f.id)
}

/** List files of the current user（裸数组契约，返回已归一的 FileItem[]）。 */
export async function listFiles(params?: FileListParams): Promise<FileItem[]> {
  const res = await api.get<unknown>(BASE, { params })
  return normalizeFileInfoList(res)
}

/** Upload a file (multipart). */
export function uploadFile(formData: FormData) {
  return request.post(`${BASE}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }) as unknown as Promise<ApiResponse<FileItem>>
}

/** Get file content as text. */
export function getFileContent(id: string): Promise<string> {
  // 后端 `GET /api/v1/files/{id}/content` 回 `{file_id, filename, mime_type, content}`
  // （files_api.py）；此前前端类型写成裸字符串、页面靠 `typeof res === 'string'`
  // 兜底，于是预览里显示的是整个 JSON 外壳。这里收口成取 `.content`，
  // 与后端的真实返回形状单源一致（二进制文件后端显式 415，不静默回空串）。
  return api.get<{ content: string }>(`${BASE}/${id}/content`).then((res) => res.content)
}

/** Get version history for a file.
 *  后端回 `{code, data:{versions:[...]}}` 信封（files_api.py:602），此处只声明形状，
 *  解数组的责任在消费方（与裸/信封并存的其余端点同一口径）。 */
export function getFileVersions(id: string) {
  return api.get<{ code: number; data: { versions: FileVersion[] } }>(`${BASE}/${id}/versions`)
}

/** Update file metadata. */
export function updateFile(id: string, data: Partial<FileItem>) {
  return api.put<ApiResponse<FileItem>>(`${BASE}/${id}`, data)
}

/** Delete a file. */
export function deleteFile(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Download a file (returns blob). */
export function downloadFile(id: string) {
  return request.get(`${BASE}/${id}/download`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** Get raw preview bytes（图片等二进制预览；带 JWT 走 axios，直链必 401）。
 *  后端 `GET /files/{id}/preview` 以 FileResponse 回原始字节（files_api.py:511），
 *  此前前端零消费者——预览弹窗里图片分支永远落空（P1-22 同链断点）。 */
export function getFilePreview(id: string) {
  return request.get(`${BASE}/${id}/preview`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/**
 * Extract file_id from a POST /files/upload response.
 *
 * Backend contract: FileInfo serializes the key as `file_id` (no `id` field,
 * no envelope). Accepts an envelope-wrapped shape (.data) and an `id` alias;
 * returns null when the response carries neither.
 */
export function extractUploadedFileId(res: unknown): string | null {
  const body =
    res && typeof res === 'object' && 'data' in res
      ? (res as { data?: unknown }).data ?? res
      : res
  if (!body || typeof body !== 'object') return null
  const fid = (body as Record<string, unknown>).file_id ?? (body as Record<string, unknown>).id
  return typeof fid === 'string' && fid ? fid : null
}

/** 后端 `GET /files/storage/info` 的裸 `StorageInfo`（files_api.py:81，无配额语义）。 */
export interface StorageInfo {
  user_id: string
  total_files: number
  total_size: number
  by_type: Record<string, number>
}

/** 存储用量读数（S6 移交·用户拍板 2026-11-17：存储卡接真实总量/已用，不造配额百分比）。 */
export async function getStorageInfo(): Promise<StorageInfo> {
  const res = await api.get<StorageInfo>(`${BASE}/storage/info`)
  return res
}

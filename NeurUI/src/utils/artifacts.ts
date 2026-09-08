/**
 * 工具产物（artifact）解析与 dock 开 tab 钩子（产物预览计划 W4，2026-09-08）。
 *
 * 数据面双保险：
 * - 后端已就位时：SSE {"type":"artifact", artifact_id, kind, name, size, path}
 *   → openArtifactTab 直开；
 * - 后端事件未就位/历史回放时：parseToolResultArtifacts 从 tool_result
 *   文本提取 file_path/audio_path/output_ref.path → openPathTab（content
 *   端点按 path 反查不可行时仅开占位 tab，fetch /v1/artifacts 由后端注册 id）。
 *
 * 纯函数与 i18n/网络解耦：parse 工具只依赖字符串；开 tab 依赖 store。
 */
import { useRightDockStore, type DockTabKind } from '@/stores/rightDock'
import { api } from '@/api'

const PATH_FIELDS = ['file_path', 'audio_path', 'output_ref.path'] as const

/** 扩展名 → dock kind（与后端 artifacts_api._artifact_kind 对齐） */
const KIND_BY_EXT: Record<string, DockTabKind> = {
  md: 'markdown',
  markdown: 'markdown',
  html: 'html',
  htm: 'html',
  xhtml: 'html',
  svg: 'image',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  bmp: 'image',
  wav: 'audio',
  mp3: 'audio',
  ogg: 'audio',
  flac: 'audio',
  aac: 'audio',
  m4a: 'audio',
}

export function kindForFilename(name: string): DockTabKind {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return KIND_BY_EXT[ext] ?? 'text'
}

function basename(p: string): string {
  const norm = p.replace(/\\/g, '/')
  return norm.split('/').pop() || p
}

/** 稳定短 hash（tab id 去重键用） */
export function shortHash(s: string): string {
  let h = 5381
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0
  }
  return (h >>> 0).toString(36)
}

export interface ParsedPathRef {
  path: string
  field: string
}

/**
 * 从 tool_result 文本提取产物路径引用。
 * JSON dict 精确解析优先；截断 JSON 正则兜底（与后端同思路）。
 */
export function parseToolResultArtifacts(resultText: string): ParsedPathRef[] {
  if (!resultText || typeof resultText !== 'string') return []
  const found: ParsedPathRef[] = []
  try {
    const parsed = JSON.parse(resultText)
    if (parsed && typeof parsed === 'object') {
      for (const field of PATH_FIELDS) {
        let node: unknown = parsed
        let ok = true
        for (const part of field.split('.')) {
          if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
            node = (node as Record<string, unknown>)[part]
          } else {
            ok = false
            break
          }
        }
        if (ok && typeof node === 'string' && node && !found.some((f) => f.path === node)) {
          found.push({ path: node, field })
        }
      }
      const ref = (parsed as Record<string, unknown>).output_ref
      if (ref && typeof ref === 'object') {
        const p = (ref as Record<string, unknown>).path
        if (typeof p === 'string' && p && !found.some((f) => f.path === p)) {
          found.push({ path: p, field: 'output_ref.path' })
        }
      }
      return found
    }
  } catch {
    /* 非 JSON，走正则 */
  }
  const re = /"(file_path|audio_path|output_ref\.path)"\s*:\s*"((?:[^"\\]|\\.)*)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(resultText)) !== null) {
    let raw = m[2]
    try {
      raw = JSON.parse(`"${raw}"`) as string
    } catch {
      /* 半截转义，原样用 */
    }
    if (raw && !found.some((f) => f.path === raw)) {
      found.push({ path: raw, field: m[1] })
    }
  }
  return found
}

/** 后端 artifact 事件的载荷形态（console.py _extract_artifacts 输出） */
export interface ArtifactEventPayload {
  artifact_id: string
  kind: DockTabKind | string
  name: string
  size?: number
  path?: string
}

/** dock tab 图标 → UiIcon 线描图标名（统一图标风格，2026-09-08） */
const DOCK_ICONS: Record<DockTabKind, string> = {
  markdown: 'fileText',
  html: 'browser',
  image: 'image',
  audio: 'audio',
  text: 'file',
  history: 'clock',
  archive: 'archive',
  computer: 'monitor',
}

/**
 * SSE artifact 事件 → dock 预览 tab。
 * 内容通过 /v1/artifacts/{id}/content 按需拉取（面板内 fetch）。
 * id 统一用 path hash（与 openToolResultArtifacts 兜底通道同键，
 * 同一产物两通道只开一个 tab）。
 */
export function openArtifactTab(payload: ArtifactEventPayload): void {
  const dock = useRightDockStore()
  const kind = (KIND_BY_EXT[bucketOf(payload.name)] ?? (payload.kind as DockTabKind)) || 'text'
  // id 统一按 basename 归一：后端 artifact 事件携带绝对路径，tool_result
  // 兜底解析到的是相对路径——同一产物两通道必须命中同一 tab
  const id = payload.name
    ? `doc:p${shortHash(payload.name)}`
    : payload.path
      ? `doc:p${shortHash(payload.path.split(/[\/]/).pop() || payload.path)}`
      : `doc:${payload.artifact_id}`
  dock.openTab({
    id,
    kind,
    title: payload.name || payload.path || payload.artifact_id,
    icon: DOCK_ICONS[kind] ?? 'file',
    data: {
      artifactId: payload.artifact_id,
      path: payload.path,
    },
  })
}

function bucketOf(name: string): string {
  return name.split('.').pop()?.toLowerCase() ?? ''
}

/**
 * 从 tool_result 文本提取并打开产物 tab（后端事件缺位时的前端兜底）。
 * 返回实际打开的 tab id 列表（无产物时空数组）。
 */
export function openToolResultArtifacts(resultText: string): string[] {
  const refs = parseToolResultArtifacts(resultText)
  if (refs.length === 0) return []
  const dock = useRightDockStore()
  const ids: string[] = []
  for (const ref of refs) {
    const name = basename(ref.path)
    const kind = kindForFilename(name)
    const id = `doc:p${shortHash(name)}`
    dock.openTab({
      id,
      kind,
      title: name,
      icon: DOCK_ICONS[kind] ?? 'file',
      data: { path: ref.path },
    })
    ids.push(id)
  }
  return ids
}

/**
 * 打开代码块预览 tab（消息代码块卡片的「预览」按钮）。
 * markdown→MdPanel；html→sandbox iframe；svg/图片→ImagePanel；其余→TextPanel。
 */
export function openCodeBlockTab(code: string, language: string): void {
  const dock = useRightDockStore()
  const lang = (language || '').toLowerCase()
  let kind: DockTabKind = 'text'
  if (lang === 'markdown' || lang === 'md') kind = 'markdown'
  else if (lang === 'html' || lang === 'htm' || lang === 'xhtml') kind = 'html'
  else if (lang === 'svg') kind = 'image'
  const id = `code:${shortHash(`${lang}:${code}`)}`
  dock.openTab({
    id,
    kind,
    title: lang ? `${lang}` : 'code',
    icon: DOCK_ICONS[kind] ?? 'file',
    data: { content: code, language: lang },
  })
}

/** 打开图片直链预览（消息内联图/附件缩略图/截图） */
export function openImageTab(url: string, title: string): void {
  const dock = useRightDockStore()
  dock.openTab({
    id: `img:${shortHash(url)}`,
    kind: 'image',
    title: title || 'image',
    icon: 'image',
    data: { url },
  })
}

/** 打开用户上传文件预览（fileId 走 /v1/files/{id}/preview） */
export function openFileTab(fileId: string, name: string, mimeType?: string): void {
  const dock = useRightDockStore()
  const kind: DockTabKind =
    mimeType?.startsWith('image/') ? 'image' : kindForFilename(name) === 'text' ? 'text' : kindForFilename(name)
  dock.openTab({
    id: `file:${fileId}`,
    kind,
    title: name || fileId,
    icon: DOCK_ICONS[kind] ?? 'file',
    data: { fileId },
  })
}

/** 读取 artifact 内容文本（预览面板用；失败抛错由面板兜底展示）。
 * 注意：api 响应拦截器直接返回 response.data（此处即纯文本字符串本身）。 */
export async function fetchArtifactText(artifactId: string): Promise<string> {
  const data = (await api.get(`/artifacts/${artifactId}/content`, { responseType: 'text' })) as unknown
  if (typeof data === 'string') return data
  const wrapped = data as { data?: unknown }
  return typeof wrapped?.data === 'string' ? wrapped.data : String(data ?? '')
}

/** artifact 内容 URL（img/audio/iframe src 用） */
export function artifactContentUrl(artifactId: string): string {
  return `/api/v1/artifacts/${artifactId}/content`
}

/** 上传件内容 URL */
export function filePreviewUrl(fileId: string): string {
  return `/api/v1/files/${fileId}/preview`
}

/**
 * 附件类型分类与展示文案（单一事实源）。
 *
 * 「待发送」区的附件与「已发送」气泡里的附件是同一份数据、同一个文件类型，
 * 必须给出同一个图标与同一个体积文案。抽取（ChatPage 拆分 / 消息渲染统一为
 * 共享组件）时只搬走了分类子集，两份各自独立演进 —— ChatPage 版认
 * spreadsheet/presentation/document，composer 版不认，同一个 xlsx 在输入区
 * 与气泡里显示成不同图标。故分类集与图标映射收口到本模块，两处共用。
 *
 * 纯函数，不依赖 i18n 与网络；图标名取值域受 UiIcon.assembly.test.ts 校验。
 */

/** 附件类型分类（决定图标与缩略图着色）。 */
export function getFileCategory(type?: string): string {
  if (!type) return 'unknown'
  if (type.startsWith('image/')) return 'image'
  if (type.startsWith('audio/')) return 'audio'
  if (type.startsWith('video/')) return 'video'
  if (type === 'application/pdf') return 'pdf'
  if (type.includes('spreadsheet') || type.includes('csv')) return 'spreadsheet'
  if (type.includes('presentation') || type.includes('powerpoint')) return 'presentation'
  if (
    type.includes('document') ||
    type.includes('msword') ||
    type.includes('wordprocessing')
  )
    return 'document'
  if (type.startsWith('text/')) return 'text'
  return 'file'
}

/** 分类 → UiIcon 名称（键集须落在 ICON_SHAPES 内）。 */
const ICON_BY_CATEGORY: Record<string, string> = {
  image: 'image',
  audio: 'audio',
  video: 'image',
  pdf: 'fileText',
  spreadsheet: 'fileText',
  presentation: 'fileText',
  document: 'fileText',
  text: 'fileText',
  file: 'file',
  unknown: 'file',
}

export function getFileIcon(type?: string): string {
  return ICON_BY_CATEGORY[getFileCategory(type)] ?? 'file'
}

/** 人类可读体积（B / KB / MB）。 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

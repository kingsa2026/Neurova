import { ref } from 'vue'
import type { PendingFile } from '@/types/chat'

/**
 * 待发送附件状态（2026-09-08 ChatPage 拆分产物）。
 *
 * 模块级单例：ChatComposerArea（选择/粘贴/移除 UI）与页面编排层
 * sendMessage（快照→上传→file_ids）共享同一列表。
 * 上传仍发生在页面 sendMessage 原链路（不改写），本模块只管 UI 态。
 */

const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

const pendingFiles = ref<PendingFile[]>([])

function addFiles(files: File[]): void {
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      console.warn(`[File] ${file.name} exceeds 50MB limit, skipped`)
      continue
    }

    const pf: PendingFile = { name: file.name, file, type: file.type }
    if (file.type.startsWith('image/')) {
      pf.preview = URL.createObjectURL(file)
    }
    pendingFiles.value.push(pf)
  }
}

function removePendingFile(index: number): void {
  const pf = pendingFiles.value[index]
  if (pf?.preview) URL.revokeObjectURL(pf.preview)
  pendingFiles.value.splice(index, 1)
}

function handleFileSelect(e: Event): void {
  const target = e.target as HTMLInputElement
  if (!target.files) return
  addFiles(Array.from(target.files))
  target.value = ''
}

/** 粘贴板附件捕获（图片直贴）。返回 true 表示事件已消费（调用方 preventDefault 已内置）。 */
function handlePaste(e: ClipboardEvent): boolean {
  const items = e.clipboardData?.items
  if (!items) return false

  const files: File[] = []
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length > 0) {
    e.preventDefault()
    addFiles(files)
    return true
  }
  return false
}

/** 发送时快照并清空：attachments 元数据（消息气泡展示）+ 原始文件（上传）。 */
function takePendingForSend(): {
  attachments: Array<{ name: string; type?: string; preview?: string; size: number }>
  files: PendingFile[]
} {
  const files = [...pendingFiles.value]
  const attachments = files.map((f) => ({
    name: f.name,
    type: f.type,
    preview: f.preview,
    size: f.file.size,
  }))
  pendingFiles.value = []
  return { attachments, files }
}

export function usePendingFiles() {
  return { pendingFiles, addFiles, removePendingFile, handleFileSelect, handlePaste, takePendingForSend }
}

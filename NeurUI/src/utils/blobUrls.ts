/**
 * 消息持有的 blob object URL 生命周期助手（P1-10，2026-09-11 资源型审计）。
 *
 * blob URL 由创建方（usePendingFiles 附件预览 / ChatPage TTS 合成）转移给
 * 消息持有；消息被丢弃（切会话 clearMessages / 删轮次 removeRoundFrom /
 * 切 Agent reset / 页面卸载）时必须 revoke，否则底层 Blob 被钉死到整页刷新。
 * 字段清单与 ChatMessage 契约对齐：audioUrl、ttsUrls[]、attachments[].preview。
 */

/** 消息上可能持有 blob URL 的最小结构（ChatMessage 子集，避免耦合完整类型） */
interface BlobUrlMessage {
  audioUrl?: string
  ttsUrls?: string[]
  attachments?: Array<{ name?: string; preview?: string }>
}

/**
 * revoke 一条消息持有的全部 blob URL（只处理 `blob:` 前缀，其余原样跳过）。
 * 幂等：URL.revokeObjectURL 对已 revoke 的 URL 是规范定义的 no-op。
 */
export function revokeMessageBlobUrls(msg: BlobUrlMessage | null | undefined): void {
  if (!msg) return
  if (msg.audioUrl?.startsWith('blob:')) URL.revokeObjectURL(msg.audioUrl)
  for (const u of msg.ttsUrls ?? []) {
    if (u?.startsWith('blob:')) URL.revokeObjectURL(u)
  }
  for (const a of msg.attachments ?? []) {
    if (a.preview?.startsWith('blob:')) URL.revokeObjectURL(a.preview)
  }
}

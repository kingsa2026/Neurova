/**
 * Chat domain types shared across store, composable, and components.
 *
 * Extracted from ChatPage.vue (lines 437-469) to enable Pinia store + composable
 * consumption without circular imports. See #2 / ADR 0008.
 */

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  reasoningOpen?: boolean
  /** 流式期间是否已自动展开过思考区（用户手动折叠后不再自动打开） */
  reasoningAutoOpened?: boolean
  toolCalls?: Array<{ name: string; arguments: string; result?: string }>
  toolOpen?: boolean
  /** legacy single tool call, kept for backward compatibility */
  toolCall?: { name: string; arguments: string }
  /** legacy single tool result, kept for backward compatibility */
  toolResult?: string
  attachments?: Array<{ name: string; type?: string; preview?: string; size?: number }>
  audioUrl?: string
  audioPlaying?: boolean
  audioProgress?: number
  audioCurrentTime?: number
  audioDuration?: number
  audioSpeed?: number
  audioEl?: HTMLAudioElement | null
  ttsLoading?: boolean
  streaming?: boolean
  /** 轮次定位键 + 展示时间：用户消息 = 发送时刻；assistant 消息 = 所在轮的用户发送时刻。
   *  历史消息来自后端落盘 timestamp（同轮同戳），实时消息为客户端时钟。 */
  timestamp?: string
  /** 助手回复完成时刻（仅 assistant；流式结束后设置，用于展示"回复时间"） */
  repliedAt?: string
  /** 用户对回复质量的反馈（点赞/点踩），持久化在 session 消息 metadata */
  feedback?: 'like' | 'dislike'
  /** 流式实时 TTS 的句块 blob URL 列表（回放用；合成顺序即播放顺序） */
  ttsUrls?: string[]
  /** 回放当前句块下标 */
  ttsIdx?: number
}

export interface Session {
  id: string
  title: string
  updatedAt?: string
  /** 置顶标记（补课 2.3；后端 session 文件 pinned 字段） */
  pinned?: boolean
}

export interface PendingFile {
  name: string
  file: File
  type?: string
  preview?: string
}

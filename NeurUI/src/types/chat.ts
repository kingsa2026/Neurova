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
}

export interface Session {
  id: string
  title: string
  updatedAt?: string
}

export interface PendingFile {
  name: string
  file: File
  type?: string
  preview?: string
}

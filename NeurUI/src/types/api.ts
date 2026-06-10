export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  attachments?: ChatAttachment[]
  reasoning?: string
  toolCalls?: ToolCallInfo[]
  toolResults?: ToolResultInfo[]
  audioUrl?: string
  isStreaming?: boolean
}

export interface ChatAttachment {
  id: string
  name: string
  type: 'image' | 'document' | 'audio' | 'video' | 'file'
  url: string
  size: number
  mimeType?: string
}

export interface ToolCallInfo {
  id: string
  name: string
  arguments: Record<string, unknown>
  status: 'calling' | 'done' | 'error'
}

export interface ToolResultInfo {
  toolCallId: string
  name: string
  result: string
  isError: boolean
}

export interface ChatSession {
  id: string
  title: string
  agentId: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

export interface SSEEvent {
  type: 'reasoning' | 'tool_call' | 'tool_result' | 'message' | 'done' | 'error' | 'audio'
  data: string
}

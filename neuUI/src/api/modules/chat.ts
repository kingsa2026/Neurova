import { request } from '@/api'
import type { SendMessageRequest } from '@/api/types/ChatMessage'
import type { ApiResponse } from '@/types/auth'
import type { ChatSession } from '@/types/api'

interface ConversationsData {
  sessions?: ChatSession[]
}

/**
 * 获取会话列表
 */
export async function getConversations(agentId?: string): Promise<ChatSession[]> {
  const r = await request.get<ConversationsData>('/chat/sessions', { params: { agent_id: agentId || 'default' } })
  // 响应拦截器已返回 response.data，所以 r 是 { code, data, message }
  // 直接使用 r.data 获取实际数据
  const d = r.data || {}
  return d.sessions || []
}

import type { RawChatMessage } from '@/types/api'

interface ChatHistoryData {
  messages?: RawChatMessage[]
  history?: RawChatMessage[]
}

/**
 * 获取消息历史
 * @param agentId Agent ID
 * @param limit 返回条数
 * @param _offset 偏移量（暂未使用）
 * @param sessionId 会话 ID（可选，提供则加载该会话的历史）
 */
export async function getMessages(
  agentId: string = 'default',
  limit: number = 50,
  _offset: number = 0,
  sessionId?: string
) {
  const params: Record<string, string | number> = { agent_id: agentId, limit }
  if (sessionId) params.session_id = sessionId

  const r = await request.get<ChatHistoryData>(`/chat/history`, { params })
  const d = r.data || {}
  return (d.messages || d.history || []).map((m) => ({
    role: m.role || 'user',
    content: m.content || m.message || '',
    timestamp: typeof m.timestamp === 'number' ? m.timestamp : (m.timestamp ? new Date(m.timestamp).getTime() : Date.now()),
    // 保留思考过程和工具调用
    reasoning_content: m.reasoning_content || m.reasoning || undefined,
    tool_calls: m.tool_calls || m.tool_messages || [],
  }))
}

/**
 * 清空对话历史
 * @param agentId Agent ID
 * @param sessionId 会话 ID（可选，如果提供则只删除该会话）
 */
export async function deleteConversation(agentId: string, sessionId?: string): Promise<void> {
  const params: Record<string, string> = { agent_id: agentId }
  if (sessionId) {
    params.session_id = sessionId
  }
  await request.delete('/chat/history', { params })
}

/**
 * 发送消息（流式）
 * @param agentId Agent ID
 * @param message 消息内容
 * @param sessionId 会话 ID
 * @param callbacks 回调函数对象，用于处理不同类型的 SSE 事件
 */
import type { StreamCallbacks, StreamOptions, DownloadProgressEvent } from '@/types/api'

export async function sendMessageStream(
  agentId: string,
  message: string,
  sessionId?: string,
  callbacks?: StreamCallbacks
): Promise<void> {
  const opts: StreamOptions = {
    agent_id: agentId,
    message,
    stream: true,
  }
  if (sessionId) opts.session_id = sessionId

  // 用于缓冲不完整的 SSE 数据
  let buffer = ''

  const r = await request.post('/chat/stream', opts, {
    responseType: 'text',
    onDownloadProgress: (e: DownloadProgressEvent) => {
      if (!e.target?.responseText) return

      // 追加新数据到缓冲区
      const newText = e.target.responseText.substring(buffer.length)
      buffer += newText

      // 按双换行分割 SSE 事件
      const events = buffer.split('\n\n')

      // 保留最后一个可能不完整的事件
      buffer = events.pop() || ''

      // 处理完整的 SSE 事件
      for (const event of events) {
        if (!event.trim()) continue

        // 解析事件类型和数
        const lines = event.split('\n')
        let eventType = ''
        let dataStr = ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.substring(6).trim()
          } else if (line.startsWith('data:')) {
            dataStr = line.substring(5).trim()
          }
        }

        if (!eventType || !dataStr) continue

        try {
          const data = JSON.parse(dataStr)

          // 根据事件类型调用相应的回调
          switch (eventType) {
            case 'reasoning':
              callbacks?.onReasoning?.(data.content || '')
              break
            case 'tool_call':
              callbacks?.onToolCall?.(data.tool_name || '', data.params || {})
              break
            case 'tool_result':
              callbacks?.onToolResult?.(data.tool_name || '', data.result || '', data.success || false)
              break
            case 'message':
              callbacks?.onMessage?.(data.content || '')
              break
            case 'done':
              callbacks?.onDone?.(data.reply || '', data.attachment_ids || [])
              break
            case 'error':
              callbacks?.onError?.(data.error || '未知错误')
              break
          }
        } catch (err) {
          console.error('解析 SSE 事件失败:', err)
        }
      }
    },
  })

  // 处理缓冲区中剩余的数据
  if (buffer.trim()) {
    // 尝试解析剩余数据
    const lines = buffer.split('\n')
    let eventType = ''
    let dataStr = ''

    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventType = line.substring(6).trim()
      } else if (line.startsWith('data:')) {
        dataStr = line.substring(5).trim()
      }
    }

    if (eventType && dataStr) {
      try {
        const data = JSON.parse(dataStr)
        switch (eventType) {
          case 'reasoning':
            callbacks?.onReasoning?.(data.content || '')
            break
          case 'tool_call':
            callbacks?.onToolCall?.(data.tool_name || '', data.params || {})
            break
          case 'tool_result':
            callbacks?.onToolResult?.(data.tool_name || '', data.result || '', data.success || false)
            break
          case 'message':
            callbacks?.onMessage?.(data.content || '')
            break
          case 'done':
            callbacks?.onDone?.(data.reply || '', data.attachment_ids || [])
            break
          case 'error':
            callbacks?.onError?.(data.error || '未知错误')
            break
        }
      } catch (err) {
        console.error('解析剩余 SSE 数据失败:', err)
      }
    }
  }
}

import type { SendMessageResult, MediaUploadResult } from '@/types/api'

interface SendMessageOptions {
  agent_id: string
  message: string
  stream: boolean
  save_memory: boolean
  session_id?: string
  attachments?: SendMessageRequest['attachments']
}

/**
 * 发送消息（非流式）
 */
export async function sendMessage(params: SendMessageRequest): Promise<SendMessageResult> {
  const opts: SendMessageOptions = {
    agent_id: params.agent_id || 'default',
    message: params.message,
    stream: params.stream ?? false,
    save_memory: params.save_memory ?? true,
  }
  if (params.session_id) opts.session_id = params.session_id
  if (params.attachments?.length) opts.attachments = params.attachments

  const r = await request.post<SendMessageResult>('/chat', opts)
  return r.data || ({} as SendMessageResult)
}

/**
 * 上传媒体文件
 */
export async function uploadMedia(formData: FormData): Promise<MediaUploadResult> {
  const r = await request.post<MediaUploadResult>('/media/save', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return r.data || ({} as MediaUploadResult)
}

/**
 * 重命名会话
 */
export async function renameConversation(
  agentId: string,
  sessionId: string,
  newTitle: string
): Promise<void> {
  await request.put(`/chat/sessions/${sessionId}/rename`, {
    agent_id: agentId,
    title: newTitle,
  })
}

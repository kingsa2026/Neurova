import { ref, onUnmounted } from 'vue'
import type { Ref } from 'vue'
 
export interface UseStreamChatOptions {
  onMessage?: (content: string) => void
  onError?: (error: Error) => void
  onFinish?: () => void
}
 
export interface UseStreamChatReturn {
  messages: Ref<Array<{ role: 'user' | 'assistant'; content: string }>>
  isStreaming: Ref<boolean>
  currentReply: Ref<string>
  sendMessage: (message: string) => Promise<void>
  stopGeneration: () => void
}
 
export function useStreamChat(options?: UseStreamChatOptions): UseStreamChatReturn {
  const messages = ref<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const isStreaming = ref<boolean>(false)
  const currentReply = ref<string>('')
  let abortController: AbortController | null = null
 
  async function sendMessage(message: string): Promise<void> {
    if (isStreaming.value) return
 
    // 添加用户消息
    messages.value.push({
      role: 'user',
      content: message
    })
 
    isStreaming.value = true
    currentReply.value = ''
    abortController = new AbortController()
 
    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({ message }),
        signal: abortController.signal
      })
 
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
 
      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('Response body is null')
      }
 
      const decoder = new TextDecoder()
      let assistantMessage = ''
 
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
 
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')
 
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') {
              break
            }
 
            try {
              const parsed = JSON.parse(data)
              const content = parsed.choices?.[0]?.delta?.content || ''
              assistantMessage += content
              currentReply.value = assistantMessage
              if (options?.onMessage) {
                // 传递累积的内容，而不是单个 chunk
                options.onMessage(assistantMessage)
              }
            } catch (e) {
              // 忽略解析错误
            }
          }
        }
      }
 
      // 添加助手回复
      messages.value.push({
        role: 'assistant',
        content: assistantMessage
      })
 
      if (options?.onFinish) {
        options.onFinish()
      }
    } catch (error: unknown) {
      const err = error as { name?: string; message?: string }
      if (err.name !== 'AbortError') {
        if (options?.onError) {
          options.onError(err as Error)
        }
      }
    } finally {
      isStreaming.value = false
      currentReply.value = ''
      abortController = null
    }
  }
 
  function stopGeneration(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }
 
  // 组件卸载时停止生成
  onUnmounted(() => {
    stopGeneration()
  })
 
  return {
    messages,
    isStreaming,
    currentReply,
    sendMessage,
    stopGeneration
  }
}
 
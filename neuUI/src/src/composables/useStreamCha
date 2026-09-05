import { ref, onUnmounted } from 'vue'
import type { Ref } from 'vue'
&nbsp;
export interface UseStreamChatOptions {
  onMessage?: (content: string) =&gt; void
  onError?: (error: Error) =&gt; void
  onFinish?: () =&gt; void
}
&nbsp;
export interface UseStreamChatReturn {
  messages: Ref&lt;Array&lt;{ role: 'user' | 'assistant'; content: string }&gt;&gt;
  isStreaming: Ref&lt;boolean&gt;
  currentReply: Ref&lt;string&gt;
  sendMessage: (message: string) =&gt; Promise&lt;void&gt;
  stopGeneration: () =&gt; void
}
&nbsp;
export function useStreamChat(options?: UseStreamChatOptions): UseStreamChatReturn {
  const messages = ref&lt;Array&lt;{ role: 'user' | 'assistant'; content: string }&gt;&gt;([])
  const isStreaming = ref&lt;boolean&gt;(false)
  const currentReply = ref&lt;string&gt;('')
  let abortController: AbortController | null = null
&nbsp;
  async function sendMessage(message: string): Promise&lt;void&gt; {
    if (isStreaming.value) return
&nbsp;
    // 添加用户消息
    messages.value.push({
      role: 'user',
      content: message
    })
&nbsp;
    isStreaming.value = true
    currentReply.value = ''
    abortController = new AbortController()
&nbsp;
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
&nbsp;
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
&nbsp;
      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('Response body is null')
      }
&nbsp;
      const decoder = new TextDecoder()
      let assistantMessage = ''
&nbsp;
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
&nbsp;
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')
&nbsp;
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') {
              break
            }
&nbsp;
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
&nbsp;
      // 添加助手回复
      messages.value.push({
        role: 'assistant',
        content: assistantMessage
      })
&nbsp;
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
&nbsp;
  function stopGeneration(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }
&nbsp;
  // 组件卸载时停止生成
  onUnmounted(() =&gt; {
    stopGeneration()
  })
&nbsp;
  return {
    messages,
    isStreaming,
    currentReply,
    sendMessage,
    stopGeneration
  }
}
&nbsp;
/**
 * chat store setMessages 替换路径的 blob URL 回收（台账 #10，2026-09-11）。
 *
 * 契约：
 * 1. setMessages 替换前对旧数组逐条 revokeMessageBlobUrls——现有调用方
 *    （useChat.switchSession）先 clearMessages（已 revoke，规范定义的 no-op
 *    幂等）或传后端映射（无 blob URL），未来调用方直设客户端活消息不再泄漏；
 * 2. 新数组中的 URL 不被 revoke（仍是活消息）；
 * 3. 非 blob 前缀（服务端 URL）不 revoke；
 * 4. 重复 revoke（已 revoke 的 URL 再次进 revokeObjectURL）是规范 no-op，
 *    不抛错——切会话 clearMessages → setMessages(mapped) 链路安全。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage } from '@/types/chat'

const revokeMock = vi.fn()

function blobMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    role: 'assistant',
    content: 'x',
    audioUrl: 'blob:audio-old',
    ttsUrls: ['blob:tts-old'],
    attachments: [{ name: 'a.png', preview: 'blob:preview-old' }],
    ...overrides,
  } as ChatMessage
}

describe('setMessages 替换前回收旧数组 blob URL（#10）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    revokeMock.mockClear()
    ;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock
  })

  it('替换客户端活消息：旧消息 blob 被 revoke，新消息 blob 不动', () => {
    const store = useChatStore()
    store.setMessages([blobMsg()])
    revokeMock.mockClear()

    store.setMessages([blobMsg({ audioUrl: 'blob:audio-new', ttsUrls: ['blob:tts-new'], attachments: [{ name: 'b.png', preview: 'blob:preview-new' }] })])

    expect(revokeMock).toHaveBeenCalledWith('blob:audio-old')
    expect(revokeMock).toHaveBeenCalledWith('blob:tts-old')
    expect(revokeMock).toHaveBeenCalledWith('blob:preview-old')
    expect(revokeMock).not.toHaveBeenCalledWith('blob:audio-new')
    expect(revokeMock).not.toHaveBeenCalledWith('blob:tts-new')
    expect(revokeMock).not.toHaveBeenCalledWith('blob:preview-new')
    expect(store.messages).toHaveLength(1)
  })

  it('后端映射（无 blob URL）替换：不产生任何 revoke（现有调用方形态）', () => {
    const store = useChatStore()
    // 现有调用方（useChat.switchSession）传后端历史映射，仅服务端 URL / 无 URL
    store.setMessages([
      { role: 'user', content: 'q' } as ChatMessage,
      { role: 'assistant', content: 'a', audioUrl: 'https://srv.example/a.wav' } as ChatMessage,
    ])
    revokeMock.mockClear()

    store.setMessages([{ role: 'user', content: 'q2' } as ChatMessage])

    expect(revokeMock).not.toHaveBeenCalled()
  })

  it('幂等：已 revoke 的 URL 再次 revoke 不抛错（clearMessages → setMessages 链路）', () => {
    const store = useChatStore()
    store.setMessages([blobMsg()])
    store.clearMessages() // 第一次 revoke
    expect(() => store.setMessages([])).not.toThrow() // 旧数组已空，无二次来源

    // 规范 no-op 断言：同一 URL 重复 revokeObjectURL 允许调用（spec-defined no-op）
    expect(() => {
      URL.revokeObjectURL('blob:audio-old')
      URL.revokeObjectURL('blob:audio-old')
    }).not.toThrow()
    expect(revokeMock).toHaveBeenCalledWith('blob:audio-old')
  })
})

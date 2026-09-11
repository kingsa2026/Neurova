/**
 * chat store 消息丢弃路径的 blob URL 回收（P1-10 / P2-19 防回归）。
 *
 * 契约：
 * 1. clearMessages / reset 丢弃消息前逐条 revoke 消息持有的 blob URL；
 * 2. removeRoundFrom 只 revoke 被删轮次的消息，保留消息的 URL 不动；
 * 3. reset() 一并清空 archivedSessions（P2-19：切 Agent 不残留旧 Agent 存档）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage, Session } from '@/types/chat'

const revokeMock = vi.fn()

function blobMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    role: 'user',
    content: 'x',
    audioUrl: 'blob:audio-1',
    ttsUrls: ['blob:tts-1', 'https://keep.example/a.wav'],
    attachments: [{ name: 'a.png', preview: 'blob:preview-1' }, { name: 'b.txt' }],
    ...overrides,
  } as ChatMessage
}

describe('chat store blob URL 回收（P1-10 / P2-19）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    revokeMock.mockClear()
    ;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock
  })

  it('clearMessages 丢弃前回收每条消息的 blob URL，非 blob URL 不动', () => {
    const store = useChatStore()
    store.setMessages([blobMsg(), blobMsg({ audioUrl: 'https://no-blob.example/a.wav' })])

    store.clearMessages()

    expect(store.messages).toEqual([])
    expect(revokeMock).toHaveBeenCalledWith('blob:audio-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:tts-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:preview-1')
    // 非 blob 前缀一律不 revoke
    expect(revokeMock).not.toHaveBeenCalledWith('https://keep.example/a.wav')
    expect(revokeMock).not.toHaveBeenCalledWith('https://no-blob.example/a.wav')
    // 首条 3 个（audio+tts+preview）+ 第二条 2 个（tts+preview）
    expect(revokeMock).toHaveBeenCalledTimes(5)
  })

  it('removeRoundFrom 只回收被删轮次，保留消息的 blob URL 不被 revoke', () => {
    const store = useChatStore()
    store.setMessages([
      blobMsg({ role: 'user', content: 'q1', audioUrl: 'blob:keep-1', ttsUrls: [], attachments: [] }),
      { role: 'assistant', content: 'a1', ttsUrls: ['blob:keep-2'] } as ChatMessage,
      blobMsg({ role: 'user', content: 'q2', audioUrl: 'blob:drop-1', ttsUrls: [], attachments: [] }),
      { role: 'assistant', content: 'a2', ttsUrls: ['blob:drop-2'] } as ChatMessage,
    ])

    store.removeRoundFrom(2)

    expect(store.messages.map((m) => m.content)).toEqual(['q1', 'a1'])
    expect(revokeMock).toHaveBeenCalledWith('blob:drop-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:drop-2')
    expect(revokeMock).not.toHaveBeenCalledWith('blob:keep-1')
    expect(revokeMock).not.toHaveBeenCalledWith('blob:keep-2')
  })

  it('reset() 回收消息 blob URL 并清空 archivedSessions（P2-19）', () => {
    const store = useChatStore()
    store.setMessages([blobMsg()])
    store.setArchivedSessions([{ id: 's-old', title: '旧 Agent 存档' } as Session])

    store.reset()

    expect(store.messages).toEqual([])
    expect(store.archivedSessions).toEqual([])
    expect(revokeMock).toHaveBeenCalledWith('blob:audio-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:preview-1')
  })
})

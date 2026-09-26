/**
 * 会话时间线消费面（Issue #262）——红灯切片。
 *
 * 后端 timeline 端点 + append-only JSONL 已建，前端零消费者：
 * SSE 断线后缺的那些事件在浏览器侧无处可取。本文件钉住
 * useChat 的 timeline 补课契约（取数 → 归一 → 并入 store）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('@/api/modules/console', () => ({
  deleteConsoleSession: vi.fn(),
  archiveConsoleSession: vi.fn(),
  unarchiveConsoleSession: vi.fn(),
  getConsoleSessionTimeline: vi.fn(),
}))

vi.mock('@/bus', () => {
  const handlers: Record<string, Array<(payload: unknown) => void>> = {}
  return {
    default: {
      on: vi.fn((type: string, handler: (p: unknown) => void) => {
        ;(handlers[type] ||= []).push(handler)
      }),
      off: vi.fn(),
      emit: vi.fn((type: string, payload: unknown) => {
        ;(handlers[type] || []).forEach((h) => h(payload))
      }),
      clear: vi.fn(() => {
        for (const k of Object.keys(handlers)) delete handlers[k]
      }),
    },
  }
})

import api from '@/api'
import { getConsoleSessionTimeline } from '@/api/modules/console'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chat'

const mockTimeline = vi.mocked(getConsoleSessionTimeline)

function timelineResponse(events: unknown[]) {
  return {
    code: 0,
    message: 'success',
    data: { session_id: 's1', events, total: events.length },
  } as unknown as Awaited<ReturnType<typeof getConsoleSessionTimeline>>
}

describe('useChat.replaySessionTimeline', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('取回的轮次并入 store（补课到当前会话）', async () => {
    mockTimeline.mockResolvedValueOnce(
      timelineResponse([
        { type: 'chunk', content: '你好' },
        { type: 'done', session_id: 's1' },
      ]),
    )

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('s1')
    store.clearMessages()

    const result = await replaySessionTimeline('s1')

    expect(mockTimeline).toHaveBeenCalledWith('s1', 0)
    expect(result.ok).toBe(true)
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('你好')
  })

  it('skipRounds 快进：已渲染轮不再重复追加', async () => {
    mockTimeline.mockResolvedValueOnce(
      timelineResponse([
        { type: 'chunk', content: '一轮' },
        { type: 'done' },
        { type: 'chunk', content: '二轮' },
        { type: 'done' },
      ]),
    )

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('s1')
    store.clearMessages()

    const result = await replaySessionTimeline('s1', { skipRounds: 1 })

    expect(result.ok).toBe(true)
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('二轮')
  })

  it('时间线为空时不写任何消息（不造幽灵轮）', async () => {
    mockTimeline.mockResolvedValueOnce(timelineResponse([]))

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('s1')
    store.clearMessages()

    const result = await replaySessionTimeline('s1')

    expect(result.ok).toBe(true)
    expect(store.messages).toHaveLength(0)
  })

  it('非当前会话的补课结果不写入 store（会话已切走）', async () => {
    mockTimeline.mockResolvedValueOnce(
      timelineResponse([{ type: 'chunk', content: '不该出现' }, { type: 'done' }]),
    )

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('other-session')
    store.clearMessages()

    const result = await replaySessionTimeline('s1')

    expect(result.ok).toBe(true)
    expect(store.messages).toHaveLength(0)
  })

  it('请求失败返回 ok:false 且不改动消息', async () => {
    mockTimeline.mockRejectedValueOnce(new Error('network down'))

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('s1')
    store.clearMessages()

    const result = await replaySessionTimeline('s1')

    expect(result.ok).toBe(false)
    expect(store.messages).toHaveLength(0)
  })

  it('continueTail 时对既有末条 assistant 消息补差量', async () => {
    mockTimeline.mockResolvedValueOnce(
      timelineResponse([{ type: 'chunk', content: '甲乙丙' }]),
    )

    const { replaySessionTimeline, store } = useChat()
    store.setCurrentSession('s1')
    store.clearMessages()
    store.addMessage({ role: 'assistant', content: '甲乙', steps: [] })

    const result = await replaySessionTimeline('s1', { continueTail: true })

    expect(result.ok).toBe(true)
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('甲乙丙')
  })
})

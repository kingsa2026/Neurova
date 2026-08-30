/**
 * useChat.switchSession — 历史消息 reasoning 回放契约测试（R-2）
 *
 * 背景根因（R-2）: 后端 post_chat 管线把 reasoning_content 存入 assistant 消息的
 * metadata（post_chat_pipeline._step_save_session → assistant_metadata → add_message），
 * 历史回放时前端此前只读顶层 m.reasoning / m.reasoning_content，metadata 内的
 * 思考过程被忽略 → 切换页面重新打开会话后思考过程不显示。
 *
 * 修复契约:
 *   1. m.metadata.reasoning_content 必须映射为消息的 reasoning 字段
 *      （同时兼容顶层 m.reasoning_content / m.reasoning）
 *   2. 带 reasoning 的历史消息默认展开（reasoningOpen=true），与实时流式首片
 *      自动展开行为一致
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/api/modules/console', () => ({
  deleteConsoleSession: vi.fn(),
  archiveConsoleSession: vi.fn(),
  unarchiveConsoleSession: vi.fn(),
}))

vi.mock('@/bus', () => ({
  default: { on: vi.fn(), off: vi.fn(), emit: vi.fn(), clear: vi.fn() },
}))

import api from '@/api'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chat'

describe('useChat.switchSession — reasoning 历史回放', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('metadata.reasoning_content 映射为 reasoning 且默认展开', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        messages: [
          { role: 'user', content: 'Q1', timestamp: 't1' },
          {
            role: 'assistant',
            content: 'A1',
            timestamp: 't1',
            metadata: { reasoning_content: '思考过程 A' },
          },
        ],
      },
    } as any)

    const { switchSession, store } = useChat()
    const res = await switchSession('sess-r2-1')
    expect(res.ok).toBe(true)

    const asst = store.messages[1]
    expect(asst.reasoning).toBe('思考过程 A')
    expect(asst.reasoningOpen, '带思考过程的历史消息应默认展开').toBe(true)
  })

  it('兼容顶层 reasoning_content 字段（旧数据/其他通道）', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        messages: [
          { role: 'user', content: 'Q1', timestamp: 't1' },
          { role: 'assistant', content: 'A1', reasoning_content: '顶层思考', timestamp: 't1' },
        ],
      },
    } as any)

    const { switchSession, store } = useChat()
    await switchSession('sess-r2-2')
    expect(store.messages[1].reasoning).toBe('顶层思考')
    expect(store.messages[1].reasoningOpen).toBe(true)
  })

  it('无 reasoning 的历史消息保持折叠', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        messages: [
          { role: 'user', content: 'Q1', timestamp: 't1' },
          { role: 'assistant', content: 'A1', timestamp: 't1' },
        ],
      },
    } as any)

    const { switchSession, store } = useChat()
    await switchSession('sess-r2-3')
    expect(store.messages[1].reasoning).toBeUndefined()
    expect(store.messages[1].reasoningOpen).toBe(false)
  })
})

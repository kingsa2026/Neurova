import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock the API modules before importing the composable.
vi.mock('@/api', () => {
  return {
    default: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  }
})

vi.mock('@/api/modules/console', () => ({
  deleteConsoleSession: vi.fn(),
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
import { deleteConsoleSession } from '@/api/modules/console'
import bus from '@/bus'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chat'

describe('useChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // -------------------------------------------------------------------------
  // loadSessions
  // -------------------------------------------------------------------------

  describe('loadSessions', () => {
    it('loads sessions and maps fields correctly', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: {
          sessions: [
            { session_id: 's1', title: 'Alpha', created_at: '2026-01-01' },
            { id: 's2', name: 'Beta', updated_at: '2026-02-01' },
          ],
        },
      } as any)

      const { loadSessions, store } = useChat()
      await loadSessions('agent-1')

      expect(api.get).toHaveBeenCalledWith('/console/chat/sessions?agent_id=agent-1')
      expect(store.sessions).toHaveLength(2)
      expect(store.sessions[0]).toEqual({
        id: 's1',
        title: 'Alpha',
        updatedAt: '2026-01-01',
      })
      expect(store.sessions[1]).toEqual({
        id: 's2',
        title: 'Beta',
        updatedAt: '2026-02-01',
      })
    })

    it('auto-selects the first session when none is active', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { sessions: [{ session_id: 's1', title: 'A' }] },
      } as any)
      // switchSession will trigger a second api.get for history
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { loadSessions, store } = useChat()
      await loadSessions('agent-1')

      expect(store.currentSessionId).toBe('s1')
    })

    it('does not auto-select when a session is already active', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { sessions: [{ session_id: 's1', title: 'A' }] },
      } as any)

      const { loadSessions, store } = useChat()
      store.setCurrentSession('existing')
      await loadSessions('agent-1')

      expect(store.currentSessionId).toBe('existing')
    })

    it('clears sessions on API error', async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error('network'))
      const { loadSessions, store } = useChat()
      store.setSessions([{ id: 'old', title: 'old' }])

      await loadSessions('agent-1')

      expect(store.sessions).toEqual([])
    })

    it('handles missing agent_id gracefully', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({ data: { sessions: [] } } as any)
      const { loadSessions } = useChat()
      await loadSessions('')
      expect(api.get).toHaveBeenCalledWith('/console/chat/sessions')
    })

    // ── chat.loadHistoryFailed 修复契约 (遗留边界情况) ──────────────
    // loadSessions auto-select 第一个 session 是副作用, 历史加载失败不应弹 toast
    // 让用户误以为页面加载失败. 原因: switchSession 接口不再 toast (返回
    // SwitchResult), 调用方 (loadSessions) 静默消费失败结果.
    it('auto-selecting first session on history load failure does NOT call onError (side-effect, silent)', async () => {
      // sessions list 加载成功
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { sessions: [{ session_id: 's1', title: 'A' }] },
      } as any)
      // switchSession 内部 GET history 失败 (模拟 session 后端不存在)
      vi.mocked(api.get).mockRejectedValueOnce(new Error('history 404'))

      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { loadSessions, store } = useChat({ onError, errorMessage })
      await loadSessions('agent-1')

      // 副作用: session 列表已加载, currentSessionId 已切换
      expect(store.sessions).toHaveLength(1)
      expect(store.currentSessionId).toBe('s1')
      // 关键契约: 不应弹"加载历史对话失败"toast (页面加载的副作用)
      expect(onError).not.toHaveBeenCalledWith('加载历史对话失败')
    })
  })

  // -------------------------------------------------------------------------
  // createSession
  // -------------------------------------------------------------------------

  describe('createSession', () => {
    it('sends agent_id and title in the POST body (multi-agent isolation)', async () => {
      vi.mocked(api.post).mockResolvedValueOnce({ data: { session_id: 'new-1' } } as any)
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)
      const { createSession } = useChat()
      await createSession('agent-1', 'My Chat')
      expect(api.post).toHaveBeenCalledWith('/console/chat/new', {
        agent_id: 'agent-1',
        title: 'My Chat',
      })
    })

    it('creates session on backend, prepends to store, and switches to it', async () => {
      vi.mocked(api.post).mockResolvedValueOnce({
        data: { session_id: 'new-1' },
      } as any)
      // switchSession triggers a history load
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { createSession, store } = useChat()
      const newId = await createSession('agent-1', '新对话')

      expect(api.post).toHaveBeenCalledWith('/console/chat/new', { agent_id: 'agent-1', title: '新对话' })
      expect(newId).toBe('new-1')
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('new-1')
      expect(store.currentSessionId).toBe('new-1')
    })

    it('emits chat:session-created event on the bus', async () => {
      vi.mocked(api.post).mockResolvedValueOnce({
        data: { session_id: 'new-1' },
      } as any)
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { createSession } = useChat()
      await createSession('agent-1')

      expect(bus.emit).toHaveBeenCalledWith('chat:session-created', {
        sessionId: 'new-1',
        agentId: 'agent-1',
      })
    })

    it('returns null and calls onError on API failure', async () => {
      vi.mocked(api.post).mockRejectedValueOnce(new Error('server'))
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { createSession } = useChat({ onError, errorMessage })
      const result = await createSession('agent-1')

      expect(result).toBeNull()
      expect(onError).toHaveBeenCalledWith('创建会话失败')
    })

    // ── 幽灵 session 防御 (chat.loadHistoryFailed toast 根因修复) ───────
    // 旧契约: 后端不返回 session_id 时 fallback 到 crypto.randomUUID() 生成
    // 前端 UUID, 但这个 UUID 后端不知道, 存到 store 后用户点击它 GET /history
    // → 404 → toast "加载历史对话失败" (chat.loadHistoryFailed raw key bug).
    // 新契约: 后端不返回 session_id 时返回 null + 弹 toast, 不创建幽灵 session.
    // 详见 docs/bugfix-delete-session-userid-mismatch.md "幽灵 session 自愈".
    it('returns null and does NOT create ghost session when backend omits session_id (no UUID fallback)', async () => {
      // 后端返回 200 但 data 里没有 session_id (异常响应, 例如旧版本后端)
      vi.mocked(api.post).mockResolvedValueOnce({ data: {} } as any)
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { createSession, store } = useChat({ onError, errorMessage })
      const result = await createSession('agent-1')

      // 关键: 不创建幽灵 session (无 UUID fallback)
      expect(result).toBeNull()
      expect(store.sessions).toHaveLength(0)
      // 弹 toast 提示用户创建失败
      expect(onError).toHaveBeenCalled()
      expect(errorMessage).toHaveBeenCalledWith('chat.createSessionFailed', '创建会话失败')
    })

    // ── chat.loadHistoryFailed 修复契约 (createSession 副作用) ───────
    // 创建会话已成功, 但 switchSession 加载新会话历史失败时, 不应弹
    // "加载历史对话失败" toast 掩盖创建成功结果. 原因: switchSession 接口
    // 不再 toast, createSession 静默消费失败结果.
    it('does NOT call onError when post-create history load fails (creation succeeded, side-effect silent)', async () => {
      // 创建成功
      vi.mocked(api.post).mockResolvedValueOnce({
        data: { session_id: 'new-1' },
      } as any)
      // switchSession 内部 GET history 失败
      vi.mocked(api.get).mockRejectedValueOnce(new Error('history 404'))

      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { createSession, store } = useChat({ onError, errorMessage })
      const newId = await createSession('agent-1')

      // 创建已成功 (不应被历史加载失败拖累)
      expect(newId).toBe('new-1')
      expect(store.sessions[0].id).toBe('new-1')
      expect(store.currentSessionId).toBe('new-1')
      // 关键契约: 不应弹"加载历史对话失败"toast
      expect(onError).not.toHaveBeenCalledWith('加载历史对话失败')
    })
  })

  // -------------------------------------------------------------------------
  // switchSession
  // -------------------------------------------------------------------------

  describe('switchSession', () => {
    it('sets current session, clears messages, and loads history', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: [
          { role: 'user', content: 'hello' },
          { role: 'assistant', content: 'hi there' },
        ],
      } as any)

      const { switchSession, store } = useChat()
      store.addMessage({ role: 'user', content: 'stale' })

      await switchSession('s1')

      expect(store.currentSessionId).toBe('s1')
      expect(store.messages).toHaveLength(2)
      expect(store.messages[0]).toEqual({
        role: 'user',
        content: 'hello',
        reasoningOpen: false,
        toolCall: undefined,
        toolResult: undefined,
      })
    })

    it('maps tool_messages into toolCalls array', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: [
          {
            role: 'assistant',
            content: 'let me check',
            tool_messages: [
              { type: 'tool_call', tool_name: 'weather', params: { city: '北京' } },
              { type: 'tool_result', result: { temp: 25 } },
            ],
          },
        ],
      } as any)

      const { switchSession, store } = useChat()
      await switchSession('s1')

      expect(store.messages[0].toolCalls).toHaveLength(1)
      expect(store.messages[0].toolCalls![0].name).toBe('weather')
      expect(store.messages[0].toolCalls![0].arguments).toContain('北京')
      expect(store.messages[0].toolCalls![0].result).toContain('25')
    })

    it('emits chat:session-switched event', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { switchSession } = useChat()
      await switchSession('s1')

      expect(bus.emit).toHaveBeenCalledWith('chat:session-switched', {
        sessionId: 's1',
      })
    })

    // ── SwitchResult 契约 (架构深化: silent boolean → result 类型) ──────
    // switchSession 不再内部弹 toast, 错误策略由调用方 own:
    //   - loadSessions/createSession/deleteSession (副作用调用): 静默
    //   - ChatPage.switchSession wrapper (用户主动): 调 notifySwitchFailure

    it('returns { ok: true } on successful history load', async () => {
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)
      const { switchSession } = useChat()
      const result = await switchSession('s1')
      expect(result).toEqual({ ok: true })
    })

    it('returns { ok: false, error } and clears messages on API error (does NOT call onError — caller decides)', async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error('server'))
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { switchSession, store } = useChat({ onError, errorMessage })
      const result = await switchSession('s1')

      expect(result.ok).toBe(false)
      expect((result as any).error).toBeInstanceOf(Error)
      expect(store.messages).toEqual([])
      // 新契约: switchSession 不再内部弹 toast, 由调用方通过 notifySwitchFailure 决定
      expect(onError).not.toHaveBeenCalled()
    })

    // ── 幽灵 session 自愈 (chat.loadHistoryFailed toast 根因修复) ───────
    // 场景: sidebar 里有后端不存在的 session (幽灵 session, 例如前端 UUID
    // fallback 残留), 用户点击它 GET /history → 404.
    // 旧契约: catch 块仅 console.error + return { ok: false }, 幽灵 session
    // 永远留在 sidebar, 用户每次点击都触发 toast.
    // 新契约: 404 时自动从 store 移除该 session, 自愈清理, 避免反复 toast.
    // 详见 docs/bugfix-delete-session-userid-mismatch.md "幽灵 session 自愈".
    it('auto-removes ghost session from store on 404 (self-healing)', async () => {
      // 模拟 axios 404 错误: error.response.status === 404
      const err: any = new Error('Request failed with status code 404')
      err.response = { status: 404 }
      vi.mocked(api.get).mockRejectedValueOnce(err)

      const { switchSession, store } = useChat()
      // 预置 store: 含一个幽灵 session 和一个真实 session
      store.setSessions([
        { id: 'ghost-uuid-1', title: 'Ghost' },
        { id: 'real-1', title: 'Real' },
      ])
      store.setCurrentSession('ghost-uuid-1')

      const result = await switchSession('ghost-uuid-1')

      // 失败结果仍然返回 (调用方可弹 toast 提示用户)
      expect(result.ok).toBe(false)
      // 关键自愈: 幽灵 session 被自动移除
      expect(store.sessions.find((s) => s.id === 'ghost-uuid-1')).toBeUndefined()
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('real-1')
    })

    // BUG FIX (delete-404-ghost): 幽灵 session 的 404 是"预期自愈"场景而非真错误。
    // 旧契约 catch 块无条件 console.error('[Chat] Failed to load history:', err),
    // 导致删除会话自动切换落到幽灵时, 即使删除成功且幽灵已被自愈移除,
    // 控制台仍打印一条吓人的 404 error。修复: 404 走自愈分支记录 warn (非 error)。
    it('logs a WARN (not ERROR) + returns code ghost-404 when self-healing a ghost session on 404', async () => {
      const err: any = new Error('Request failed with status code 404')
      err.response = { status: 404 }
      vi.mocked(api.get).mockRejectedValueOnce(err)

      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

      const { switchSession, store } = useChat()
      store.setSessions([
        { id: 'ghost-uuid-1', title: 'Ghost' },
        { id: 'real-1', title: 'Real' },
      ])
      store.setCurrentSession('ghost-uuid-1')

      const result = await switchSession('ghost-uuid-1')

      expect(result.ok).toBe(false)
      expect((result as any).code).toBe('ghost-404')
      // 幽灵 session 404 属预期恢复, 不应以 error 级别污染控制台
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining('Failed to load history'))
      expect(warnSpy).toHaveBeenCalled()
      // 自愈仍生效
      expect(store.sessions.find((s) => s.id === 'ghost-uuid-1')).toBeUndefined()

      errorSpy.mockRestore()
      warnSpy.mockRestore()
    })

    it('does NOT remove session on non-404 error (e.g. 500, preserves session for retry)', async () => {
      // 非 404 错误 (如服务器 500) 不应删除 session, 因为 session 可能仍然有效
      // (例如后端临时故障, 重试可能成功)
      const err: any = new Error('Request failed with status code 500')
      err.response = { status: 500 }
      vi.mocked(api.get).mockRejectedValueOnce(err)

      const { switchSession, store } = useChat()
      store.setSessions([{ id: 's1', title: 'Session 1' }])

      const result = await switchSession('s1')

      expect(result.ok).toBe(false)
      // 服务器错误: 保留 session (不是它的错, 重试可能恢复)
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('s1')
    })

    it('does NOT remove session on network error (no response.status, preserves session)', async () => {
      // 网络错误 (无 response.status, 例如断网) 不应删除 session
      vi.mocked(api.get).mockRejectedValueOnce(new Error('Network Error'))

      const { switchSession, store } = useChat()
      store.setSessions([{ id: 's1', title: 'Session 1' }])

      const result = await switchSession('s1')

      expect(result.ok).toBe(false)
      // 网络错误: 保留 session
      expect(store.sessions).toHaveLength(1)
    })
  })

  // -------------------------------------------------------------------------
  // notifySwitchFailure — 用户主动场景的错误策略 helper
  // -------------------------------------------------------------------------
  describe('notifySwitchFailure', () => {
    it('calls onError with i18n message when result is failure', () => {
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => `i18n:${k}/${f}`)
      const { notifySwitchFailure } = useChat({ onError, errorMessage })

      notifySwitchFailure({ ok: false, error: new Error('history 404') })

      expect(errorMessage).toHaveBeenCalledWith('chat.loadHistoryFailed', '加载历史对话失败')
      expect(onError).toHaveBeenCalledWith('i18n:chat.loadHistoryFailed/加载历史对话失败')
    })

    it('does NOT call onError when result is ok', () => {
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)
      const { notifySwitchFailure } = useChat({ onError, errorMessage })

      notifySwitchFailure({ ok: true })

      expect(onError).not.toHaveBeenCalled()
    })

    it('falls back to hardcoded message when errorMessage option is absent', () => {
      const onError = vi.fn()
      const { notifySwitchFailure } = useChat({ onError })

      notifySwitchFailure({ ok: false, error: new Error('boom') })

      expect(onError).toHaveBeenCalledWith('加载历史对话失败')
    })
  })

  // -------------------------------------------------------------------------
  // deleteSession — DeleteResult 契约 (架构深化: boolean → discriminated union)
  // -------------------------------------------------------------------------
  // 与 switchSession 的 SwitchResult 模式平行:
  //   - deleteSession 不再内部弹 toast, 仅返回 { ok: true | false, error? }
  //   - 错误策略由调用方 own:
  //     * 副作用调用 (无): 无
  //     * 用户主动调用 (ChatPage.deleteSession wrapper): 调 notifyDeleteFailure
  //   - 替换原 `return false` 浅返回模式 — 接口不再吞错, 调用方决策空间完整.
  //   - 详见 docs/bugfix-delete-session-userid-mismatch.md "前端错误反馈策略深化" 小节.

  describe('deleteSession', () => {
    it('deletes on backend, removes from store, returns { ok: true }', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      const { deleteSession, store } = useChat()
      store.setSessions([
        { id: 's1', title: 'A' },
        { id: 's2', title: 'B' },
      ])

      const result = await deleteSession('s1')

      expect(deleteConsoleSession).toHaveBeenCalledWith('s1')
      expect(result).toEqual({ ok: true })
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('s2')
    })

    it('emits chat:session-deleted event', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      const { deleteSession } = useChat()
      await deleteSession('s1')
      expect(bus.emit).toHaveBeenCalledWith('chat:session-deleted', {
        sessionId: 's1',
      })
    })

    it('when deleting the active session, switches to the first remaining', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      // switchSession will trigger a history load
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { deleteSession, store } = useChat()
      store.setSessions([
        { id: 's1', title: 'A' },
        { id: 's2', title: 'B' },
      ])
      store.setCurrentSession('s1')

      await deleteSession('s1')

      expect(store.currentSessionId).toBe('s2')
    })

    it('when deleting the active session with none remaining, clears current', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      const { deleteSession, store } = useChat()
      store.setSessions([{ id: 's1', title: 'A' }])
      store.setCurrentSession('s1')

      await deleteSession('s1')

      expect(store.currentSessionId).toBeNull()
      expect(store.messages).toEqual([])
    })

    // ── DeleteResult 契约 (架构深化) ──────────────────────────────────
    // Slice 2 RED: deleteSession 失败时返回 { ok: false, error }, 不调 onError.
    // 契约与 switchSession 平行 — 错误策略由调用方通过 notifyDeleteFailure 决定.
    it('returns { ok: false, error } on API failure and does NOT call onError (caller decides)', async () => {
      vi.mocked(deleteConsoleSession).mockRejectedValueOnce(new Error('403 Forbidden'))
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { deleteSession, store } = useChat({ onError, errorMessage })
      store.setSessions([{ id: 's1', title: 'A' }])

      const result = await deleteSession('s1')

      expect(result.ok).toBe(false)
      expect((result as any).error).toBeInstanceOf(Error)
      expect((result as any).error.message).toBe('403 Forbidden')
      // 失败时 session 不应从 store 移除 (removeSession 在 try 块, API 失败时不执行)
      expect(store.sessions).toHaveLength(1)
      // 关键契约: deleteSession 不内部弹 toast, 由调用方通过 notifyDeleteFailure 决定
      expect(onError).not.toHaveBeenCalled()
    })

    // BUG: chat.deleteSessionFailed — 旧契约返回 boolean, 调用方无法区分
    // "网络错误"vs"403"vs"500", 且 catch 块静默吞错 (return false) 让 UI 无反馈.
    // 修复契约: deleteSession 返回 DeleteResult discriminated union, 让错误
    // 结构流向调用方; ChatPage wrapper 调 notifyDeleteFailure 弹 toast.
    it('when deleting the active session, does NOT call onError if the auto-switched session fails to load history', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      // switchSession 内部 GET history 失败 (模拟剩余会话在后端不存在)
      vi.mocked(api.get).mockRejectedValueOnce(new Error('history 404'))

      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { deleteSession, store } = useChat({ onError, errorMessage })
      store.setSessions([
        { id: 's1', title: 'A' },
        { id: 's2', title: 'B' },
      ])
      store.setCurrentSession('s1')

      const result = await deleteSession('s1')

      // 删除本身成功 (不应被副作用失败拖累) — 返回 { ok: true }
      expect(result).toEqual({ ok: true })
      // 自动 switch 到 s2 (虽然历史加载失败, currentSessionId 应已切换)
      expect(store.currentSessionId).toBe('s2')
      // 关键契约: 不应弹"加载历史对话失败"toast, 因为这是删除操作的副作用
      expect(onError).not.toHaveBeenCalledWith('加载历史对话失败')
    })

    // BUG FIX (delete-404-ghost): 删除当前会话后自动切换, 若 store 首位是幽灵
    // session (前端 UUID 残留, 后端 404), switchSession 应自愈移除它, 且删除
    // 动效应继续尝试切换到下一个有效会话, 而不是把 UI 留在幽灵/null 上。
    // 旧契约: 仅尝试一次 store.sessions[0], 落到幽灵时打印 error 且不继续。
    it('when deleting the active session, skips ghost (404) and lands on next valid session without console.error', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      // 第一次 GET history → 幽灵 session (sessions[0]) 404
      const gErr: any = new Error('Request failed with status code 404')
      gErr.response = { status: 404 }
      const apiGetMock = vi.mocked(api.get)
      apiGetMock.mockRejectedValueOnce(gErr)
      // 第二次 GET history → 下一个真实 session 成功
      apiGetMock.mockResolvedValueOnce({ data: [] } as any)

      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

      const { deleteSession, store } = useChat()
      store.setSessions([
        { id: 'real-1', title: 'Real 1' },
        { id: 'ghost-uuid-1', title: 'Ghost' },
        { id: 'real-2', title: 'Real 2' },
      ])
      store.setCurrentSession('real-1')

      const result = await deleteSession('real-1')

      // 删除本身成功
      expect(result).toEqual({ ok: true })
      // 跳过幽灵, 落在下一个有效会话
      expect(store.currentSessionId).toBe('real-2')
      // 幽灵已被自愈移除
      expect(store.sessions.find((s) => s.id === 'ghost-uuid-1')).toBeUndefined()
      // 不应以 error 级别打印"加载历史失败"(404 是预期自愈)
      expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining('Failed to load history'))
      expect(warnSpy).toHaveBeenCalled()

      errorSpy.mockRestore()
      warnSpy.mockRestore()
    })
  })

  // -------------------------------------------------------------------------
  // notifyDeleteFailure — 用户主动删除场景的错误策略 helper
  // -------------------------------------------------------------------------
  // 与 notifySwitchFailure 平行: ChatPage.deleteSession wrapper 调用此函数,
  // 失败时弹 toast 让用户知道删除失败. 副作用调用 (无) 不调, 避免误提示.

  describe('notifyDeleteFailure', () => {
    // Slice 3 RED: notifyDeleteFailure 在失败时调 onError 弹 i18n 消息
    it('calls onError with i18n message when result is failure', () => {
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => `i18n:${k}/${f}`)
      const { notifyDeleteFailure } = useChat({ onError, errorMessage })

      notifyDeleteFailure({ ok: false, error: new Error('403 Forbidden') })

      expect(errorMessage).toHaveBeenCalledWith('chat.deleteSessionFailed', '删除会话失败')
      expect(onError).toHaveBeenCalledWith('i18n:chat.deleteSessionFailed/删除会话失败')
    })

    it('does NOT call onError when result is ok', () => {
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)
      const { notifyDeleteFailure } = useChat({ onError, errorMessage })

      notifyDeleteFailure({ ok: true })

      expect(onError).not.toHaveBeenCalled()
    })

    it('falls back to hardcoded message when errorMessage option is absent', () => {
      const onError = vi.fn()
      const { notifyDeleteFailure } = useChat({ onError })

      notifyDeleteFailure({ ok: false, error: new Error('boom') })

      expect(onError).toHaveBeenCalledWith('删除会话失败')
    })
  })

  // -------------------------------------------------------------------------
  // renameSession
  // -------------------------------------------------------------------------

  describe('renameSession', () => {
    it('PUTs the new title, updates store, returns true', async () => {
      vi.mocked(api.put).mockResolvedValueOnce({} as any)
      const { renameSession, store } = useChat()
      store.setSessions([{ id: 's1', title: 'Old' }])

      const result = await renameSession('s1', 'New Title')

      expect(api.put).toHaveBeenCalledWith('/console/chat/sessions/s1', {
        title: 'New Title',
      })
      expect(result).toBe(true)
      expect(store.sessions[0].title).toBe('New Title')
    })

    it('emits chat:session-renamed event', async () => {
      vi.mocked(api.put).mockResolvedValueOnce({} as any)
      const { renameSession } = useChat()
      await renameSession('s1', 'New')
      expect(bus.emit).toHaveBeenCalledWith('chat:session-renamed', {
        sessionId: 's1',
        title: 'New',
      })
    })

    it('trims whitespace from the title', async () => {
      vi.mocked(api.put).mockResolvedValueOnce({} as any)
      const { renameSession, store } = useChat()
      store.setSessions([{ id: 's1', title: 'Old' }])

      await renameSession('s1', '  Spaced  ')

      expect(api.put).toHaveBeenCalledWith('/console/chat/sessions/s1', {
        title: 'Spaced',
      })
      expect(store.sessions[0].title).toBe('Spaced')
    })

    it('returns false for empty title', async () => {
      const { renameSession } = useChat()
      const result = await renameSession('s1', '   ')
      expect(result).toBe(false)
      expect(api.put).not.toHaveBeenCalled()
    })

    it('returns false and calls onError on API failure', async () => {
      vi.mocked(api.put).mockRejectedValueOnce(new Error('server'))
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { renameSession } = useChat({ onError, errorMessage })
      const result = await renameSession('s1', 'New')

      expect(result).toBe(false)
      expect(onError).toHaveBeenCalledWith('重命名失败')
    })
  })

  // -------------------------------------------------------------------------
  // Loading flags
  // -------------------------------------------------------------------------

  describe('loading flags', () => {
    it('loadingSessions is true during loadSessions', async () => {
      let resolveFn!: (v: any) => void
      vi.mocked(api.get).mockReturnValueOnce(
        new Promise((resolve) => {
          resolveFn = resolve
        }) as any,
      )

      const { loadingSessions, loadSessions } = useChat()
      const promise = loadSessions('agent-1')
      expect(loadingSessions.value).toBe(true)

      resolveFn({ data: { sessions: [] } })
      await promise
      expect(loadingSessions.value).toBe(false)
    })

    it('switchingSession is true during switchSession', async () => {
      let resolveFn!: (v: any) => void
      vi.mocked(api.get).mockReturnValueOnce(
        new Promise((resolve) => {
          resolveFn = resolve
        }) as any,
      )

      const { switchingSession, switchSession } = useChat()
      const promise = switchSession('s1')
      expect(switchingSession.value).toBe(true)

      resolveFn({ data: [] })
      await promise
      expect(switchingSession.value).toBe(false)
    })
  })

  // -------------------------------------------------------------------------
  // Store passthrough
  // -------------------------------------------------------------------------

  describe('store passthrough', () => {
    it('exposes the reactive store instance', () => {
      const { store } = useChat()
      expect(store).toBe(useChatStore())
    })
  })
})

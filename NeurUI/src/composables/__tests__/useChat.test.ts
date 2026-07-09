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
  })

  // -------------------------------------------------------------------------
  // createSession
  // -------------------------------------------------------------------------

  describe('createSession', () => {
    it('creates session on backend, prepends to store, and switches to it', async () => {
      vi.mocked(api.post).mockResolvedValueOnce({
        data: { session_id: 'new-1' },
      } as any)
      // switchSession triggers a history load
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { createSession, store } = useChat()
      const newId = await createSession('agent-1', '新对话')

      expect(api.post).toHaveBeenCalledWith('/console/chat/new')
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

    it('falls back to crypto.randomUUID when backend omits session_id', async () => {
      vi.mocked(api.post).mockResolvedValueOnce({ data: {} } as any)
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any)

      const { createSession } = useChat()
      const newId = await createSession('agent-1')

      expect(newId).toBeTruthy()
      expect(newId!.length).toBeGreaterThan(10) // UUID format
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

    it('clears messages on API error and calls onError', async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error('server'))
      const onError = vi.fn()
      const errorMessage = vi.fn((k: string, f: string) => f)

      const { switchSession, store } = useChat({ onError, errorMessage })
      await switchSession('s1')

      expect(store.messages).toEqual([])
      expect(onError).toHaveBeenCalledWith('加载历史对话失败')
    })
  })

  // -------------------------------------------------------------------------
  // deleteSession
  // -------------------------------------------------------------------------

  describe('deleteSession', () => {
    it('deletes on backend, removes from store, returns true', async () => {
      vi.mocked(deleteConsoleSession).mockResolvedValueOnce({} as any)
      const { deleteSession, store } = useChat()
      store.setSessions([
        { id: 's1', title: 'A' },
        { id: 's2', title: 'B' },
      ])

      const result = await deleteSession('s1')

      expect(deleteConsoleSession).toHaveBeenCalledWith('s1')
      expect(result).toBe(true)
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

    it('returns false on API error', async () => {
      vi.mocked(deleteConsoleSession).mockRejectedValueOnce(new Error('server'))
      const { deleteSession } = useChat()
      const result = await deleteSession('s1')
      expect(result).toBe(false)
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

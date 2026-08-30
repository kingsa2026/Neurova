import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage, Session } from '@/types/chat'

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  describe('initial state', () => {
    it('starts with empty sessions', () => {
      const store = useChatStore()
      expect(store.sessions).toEqual([])
    })

    it('starts with null currentSessionId', () => {
      const store = useChatStore()
      expect(store.currentSessionId).toBeNull()
    })

    it('starts with empty messages', () => {
      const store = useChatStore()
      expect(store.messages).toEqual([])
    })

    it('starts with isStreaming false', () => {
      const store = useChatStore()
      expect(store.isStreaming).toBe(false)
    })

    it('starts with empty inputText', () => {
      const store = useChatStore()
      expect(store.inputText).toBe('')
    })

    it('starts with empty searchQuery', () => {
      const store = useChatStore()
      expect(store.searchQuery).toBe('')
    })
  })

  // -------------------------------------------------------------------------
  // Computed
  // -------------------------------------------------------------------------

  describe('computed', () => {
    it('currentSession returns undefined when no session selected', () => {
      const store = useChatStore()
      expect(store.currentSession).toBeUndefined()
    })

    it('currentSession returns the active session', () => {
      const store = useChatStore()
      const session: Session = { id: 's1', title: 'Test' }
      store.setSessions([session])
      store.setCurrentSession('s1')
      expect(store.currentSession).toEqual(session)
    })

    it('currentSessionTitle returns empty string when no session', () => {
      const store = useChatStore()
      expect(store.currentSessionTitle).toBe('')
    })

    it('currentSessionTitle returns the active session title', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'Hello' }])
      store.setCurrentSession('s1')
      expect(store.currentSessionTitle).toBe('Hello')
    })

    it('filteredSessions returns all sessions when searchQuery is empty', () => {
      const store = useChatStore()
      store.setSessions([
        { id: 's1', title: 'Alpha' },
        { id: 's2', title: 'Beta' },
      ])
      expect(store.filteredSessions).toHaveLength(2)
    })

    it('filteredSessions filters by title case-insensitively', () => {
      const store = useChatStore()
      store.setSessions([
        { id: 's1', title: 'Alpha Chat' },
        { id: 's2', title: 'Beta Session' },
      ])
      store.setSearchQuery('alpha')
      expect(store.filteredSessions).toHaveLength(1)
      expect(store.filteredSessions[0].id).toBe('s1')
    })

    it('filteredSessions filters by updatedAt', () => {
      const store = useChatStore()
      store.setSessions([
        { id: 's1', title: 'Alpha', updatedAt: '2026-01-01' },
        { id: 's2', title: 'Beta', updatedAt: '2026-06-28' },
      ])
      store.setSearchQuery('2026-06')
      expect(store.filteredSessions).toHaveLength(1)
      expect(store.filteredSessions[0].id).toBe('s2')
    })
  })

  // -------------------------------------------------------------------------
  // Session mutations
  // -------------------------------------------------------------------------

  describe('session mutations', () => {
    it('setSessions replaces the list', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'A' }])
      store.setSessions([{ id: 's2', title: 'B' }])
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('s2')
    })

    it('addSession prepends to the list', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'A' }])
      store.addSession({ id: 's2', title: 'B' })
      expect(store.sessions).toHaveLength(2)
      expect(store.sessions[0].id).toBe('s2')
    })

    it('removeSession removes by id', () => {
      const store = useChatStore()
      store.setSessions([
        { id: 's1', title: 'A' },
        { id: 's2', title: 'B' },
      ])
      store.removeSession('s1')
      expect(store.sessions).toHaveLength(1)
      expect(store.sessions[0].id).toBe('s2')
    })

    it('removeSession is a no-op for unknown id', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'A' }])
      store.removeSession('unknown')
      expect(store.sessions).toHaveLength(1)
    })

    it('renameSessionTitle updates the title', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'Old' }])
      store.renameSessionTitle('s1', 'New')
      expect(store.sessions[0].title).toBe('New')
    })

    it('renameSessionTitle is a no-op for unknown id', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'Old' }])
      store.renameSessionTitle('unknown', 'New')
      expect(store.sessions[0].title).toBe('Old')
    })

    it('setCurrentSession sets the id', () => {
      const store = useChatStore()
      store.setCurrentSession('s1')
      expect(store.currentSessionId).toBe('s1')
    })

    it('setCurrentSession accepts null', () => {
      const store = useChatStore()
      store.setCurrentSession('s1')
      store.setCurrentSession(null)
      expect(store.currentSessionId).toBeNull()
    })
  })

  // -------------------------------------------------------------------------
  // Message mutations
  // -------------------------------------------------------------------------

  describe('message mutations', () => {
    it('setMessages replaces the list', () => {
      const store = useChatStore()
      const msg: ChatMessage = { role: 'user', content: 'hi' }
      store.setMessages([msg])
      expect(store.messages).toHaveLength(1)
      store.setMessages([])
      expect(store.messages).toHaveLength(0)
    })

    it('addMessage appends to the list', () => {
      const store = useChatStore()
      store.addMessage({ role: 'user', content: 'a' })
      store.addMessage({ role: 'assistant', content: 'b' })
      expect(store.messages).toHaveLength(2)
      expect(store.messages[0].content).toBe('a')
      expect(store.messages[1].content).toBe('b')
    })

    it('clearMessages empties the list', () => {
      const store = useChatStore()
      store.addMessage({ role: 'user', content: 'a' })
      store.clearMessages()
      expect(store.messages).toEqual([])
    })

    // ── 轮次删除（chat 页"删除一轮记录"） ──────────────────────────
    // removeRoundFrom(fromIndex)：移除 fromIndex 处的用户消息及其后
    // 连续的 assistant 消息（一轮），遇到下一条用户消息即停止。
    describe('removeRoundFrom', () => {
      it('removes the user message and its paired assistant reply', () => {
        const store = useChatStore()
        store.setMessages([
          { role: 'user', content: 'q1' },
          { role: 'assistant', content: 'a1' },
          { role: 'user', content: 'q2' },
          { role: 'assistant', content: 'a2' },
        ])

        store.removeRoundFrom(0)

        expect(store.messages.map((m) => m.content)).toEqual(['q2', 'a2'])
      })

      it('removes a middle round only (earlier rounds untouched)', () => {
        const store = useChatStore()
        store.setMessages([
          { role: 'user', content: 'q1' },
          { role: 'assistant', content: 'a1' },
          { role: 'user', content: 'q2' },
          { role: 'assistant', content: 'a2' },
        ])

        store.removeRoundFrom(2)

        expect(store.messages.map((m) => m.content)).toEqual(['q1', 'a1'])
      })

      it('removes a lone trailing user message (aborted stream, no reply yet)', () => {
        const store = useChatStore()
        store.setMessages([
          { role: 'user', content: 'q1' },
          { role: 'assistant', content: 'a1' },
          { role: 'user', content: 'q2-only' },
        ])

        store.removeRoundFrom(2)

        expect(store.messages.map((m) => m.content)).toEqual(['q1', 'a1'])
      })

      it('is a no-op for an out-of-range index', () => {
        const store = useChatStore()
        store.setMessages([{ role: 'user', content: 'q1' }])

        store.removeRoundFrom(5)

        expect(store.messages).toHaveLength(1)
      })
    })
  })

  // -------------------------------------------------------------------------
  // Streaming / composer mutations
  // -------------------------------------------------------------------------

  describe('streaming / composer mutations', () => {
    it('setStreaming toggles the flag', () => {
      const store = useChatStore()
      store.setStreaming(true)
      expect(store.isStreaming).toBe(true)
      store.setStreaming(false)
      expect(store.isStreaming).toBe(false)
    })

    it('setInputText updates the text', () => {
      const store = useChatStore()
      store.setInputText('hello')
      expect(store.inputText).toBe('hello')
    })

    it('setSearchQuery updates the query', () => {
      const store = useChatStore()
      store.setSearchQuery('filter')
      expect(store.searchQuery).toBe('filter')
    })
  })

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  describe('reset', () => {
    it('clears all chat state but preserves searchQuery', () => {
      const store = useChatStore()
      store.setSessions([{ id: 's1', title: 'A' }])
      store.setCurrentSession('s1')
      store.addMessage({ role: 'user', content: 'hi' })
      store.setStreaming(true)
      store.setInputText('draft')
      store.setSearchQuery('filter')

      store.reset()

      expect(store.sessions).toEqual([])
      expect(store.currentSessionId).toBeNull()
      expect(store.messages).toEqual([])
      expect(store.isStreaming).toBe(false)
      expect(store.inputText).toBe('')
      // searchQuery is intentionally preserved
      expect(store.searchQuery).toBe('filter')
    })
  })
})

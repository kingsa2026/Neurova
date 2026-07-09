import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, Session } from '@/types/chat'

/**
 * Chat store — single source of truth for chat session state.
 *
 * #2 / ADR 0008: Establishes a unified state management library for chat UI.
 * Replaces the scattered local refs in ChatPage.vue (18 ref/reactive + 4 computed
 * previously living in the component).
 *
 * State ownership:
 *   - sessions: Session[]               — list of chat sessions
 *   - currentSessionId: string | null   — active session id
 *   - messages: ChatMessage[]           — messages of the current session
 *   - isStreaming: boolean              — whether an SSE stream is in flight
 *   - inputText: string                 — composer textarea content
 *   - searchQuery: string               — sidebar session search keyword
 *
 * All mutations MUST go through the actions exposed below. Direct `.value =`
 * writes from outside the store are forbidden by convention.
 */
export const useChatStore = defineStore('chat', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref<boolean>(false)
  const inputText = ref<string>('')
  const searchQuery = ref<string>('')

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------

  /** The currently active Session object, or undefined if none selected. */
  const currentSession = computed<Session | undefined>(() =>
    sessions.value.find((s) => s.id === currentSessionId.value),
  )

  /** Sessions filtered by the sidebar search keyword. */
  const filteredSessions = computed<Session[]>(() => {
    const q = searchQuery.value.trim().toLowerCase()
    if (!q) return sessions.value
    return sessions.value.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        (s.updatedAt ?? '').toLowerCase().includes(q),
    )
  })

  /** Title of the active session, or a default placeholder. */
  const currentSessionTitle = computed<string>(() => {
    if (currentSession.value) return currentSession.value.title
    return ''
  })

  // ---------------------------------------------------------------------------
  // Session mutations
  // ---------------------------------------------------------------------------

  function setSessions(next: Session[]): void {
    sessions.value = next
  }

  /** Insert a session at the head of the list (most recent first). */
  function addSession(session: Session): void {
    sessions.value.unshift(session)
  }

  function removeSession(sessionId: string): void {
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
  }

  function renameSessionTitle(sessionId: string, title: string): void {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) session.title = title
  }

  function setCurrentSession(sessionId: string | null): void {
    currentSessionId.value = sessionId
  }

  // ---------------------------------------------------------------------------
  // Message mutations
  // ---------------------------------------------------------------------------

  function setMessages(next: ChatMessage[]): void {
    messages.value = next
  }

  function addMessage(message: ChatMessage): void {
    messages.value.push(message)
  }

  function clearMessages(): void {
    messages.value = []
  }

  // ---------------------------------------------------------------------------
  // Streaming / composer mutations
  // ---------------------------------------------------------------------------

  function setStreaming(streaming: boolean): void {
    isStreaming.value = streaming
  }

  function setInputText(text: string): void {
    inputText.value = text
  }

  function setSearchQuery(query: string): void {
    searchQuery.value = query
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /**
   * Reset all chat state. Called when switching agents or on explicit user
   * "clear" action. Does NOT clear searchQuery (user may want to keep filter).
   */
  function reset(): void {
    sessions.value = []
    currentSessionId.value = null
    messages.value = []
    isStreaming.value = false
    inputText.value = ''
  }

  return {
    // state
    sessions,
    currentSessionId,
    messages,
    isStreaming,
    inputText,
    searchQuery,
    // computed
    currentSession,
    filteredSessions,
    currentSessionTitle,
    // session mutations
    setSessions,
    addSession,
    removeSession,
    renameSessionTitle,
    setCurrentSession,
    // message mutations
    setMessages,
    addMessage,
    clearMessages,
    // streaming / composer
    setStreaming,
    setInputText,
    setSearchQuery,
    // lifecycle
    reset,
  }
})

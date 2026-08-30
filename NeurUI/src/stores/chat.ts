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
  const archivedSessions = ref<Session[]>([])
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

  // ── 存档会话（删除 → 存档：历史列表隐藏，存档卡片页可随时恢复） ──────────

  function setArchivedSessions(next: Session[]): void {
    archivedSessions.value = next
  }

  function removeArchivedSession(sessionId: string): void {
    archivedSessions.value = archivedSessions.value.filter((s) => s.id !== sessionId)
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

  /**
   * 追加消息并返回 store 中持有的引用。
   *
   * 契约（R-1 修复）: 调用方（ChatPage 流式写入）必须用返回值继续修改消息，
   * 不能沿用 push 前的原始对象引用——Vue 对 ref([]) 数组元素做 reactive 包装，
   * 原始引用写属性绕过了 proxy setter，SSE 事件不触发依赖收集，
   * 思考/正文只在下次组件重渲染时一次性出现（无法逐字显示）。
   */
  function addMessage(message: ChatMessage): ChatMessage {
    messages.value.push(message)
    return messages.value[messages.value.length - 1]
  }

  function clearMessages(): void {
    messages.value = []
  }

  /**
   * 删除一轮对话：移除 fromIndex 处的用户消息及其后连续的 assistant 消息。
   *
   * add_message 后端成对相邻写入（user+assistant），实时流式中断可能只留下
   * 孤立的尾 user 消息 — 循环遇下一条 user 消息即停止，两种情况都覆盖。
   * 供 ChatPage "删除一轮记录" 与 "编辑最后一条用户消息（删旧轮+重发）" 使用。
   */
  function removeRoundFrom(fromIndex: number): void {
    if (fromIndex < 0 || fromIndex >= messages.value.length) return
    let removedFirst = false
    let i = fromIndex
    while (i < messages.value.length) {
      // 首条（用户消息）必删；其后仅删连续的 assistant，遇下一条 user 停止。
      // splice 后后继元素前移到 i，故索引不自增，用 removedFirst 标记状态。
      if (removedFirst && messages.value[i].role !== 'assistant') break
      messages.value.splice(i, 1)
      removedFirst = true
    }
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
    archivedSessions,
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
    setArchivedSessions,
    removeArchivedSession,
    renameSessionTitle,
    setCurrentSession,
    // message mutations
    setMessages,
    addMessage,
    clearMessages,
    removeRoundFrom,
    // streaming / composer
    setStreaming,
    setInputText,
    setSearchQuery,
    // lifecycle
    reset,
  }
})

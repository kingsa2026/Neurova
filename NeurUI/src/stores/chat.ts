import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, Session } from '@/types/chat'
import { revokeMessageBlobUrls } from '@/utils/blobUrls'

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

  // ── Token 用量（QwenPaw turnUsageStore 对齐）──
  // per-session 累计（内存态，会话切换不丢；刷新即清 — 与 QwenPaw 一致）。
  // 结构：{ [sessionId]: { prompt, completion, total } }
  const sessionTokenUsage = ref<Record<string, { prompt: number; completion: number; total: number }>>({})
  /** 最近一轮的真实 usage（SSE usage 事件，消息级展示用）。 */
  const lastTurnUsage = ref<{ prompt: number; completion: number; total: number; estimated: boolean } | null>(null)

  // ── 页面级临时态（2026-09-08 composer 拆分：SSE 编排层写入、composer 读）──
  /** 实时记忆检索进度（SSE memory_progress；回复开始即清空，不落消息历史） */
  const retrievalStatus = ref('')
  /** 实时事件丢失计数（WS seq gap 检测，OpenOcta P0-1；仅提示不可恢复） */
  const eventsLostBanner = ref<number | null>(null)

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
    const base = q
      ? sessions.value.filter(
          (s) =>
            s.title.toLowerCase().includes(q) ||
            (s.updatedAt ?? '').toLowerCase().includes(q),
        )
      : sessions.value
    // 置顶优先（补课 2.3），其余保持原有顺序
    return [...base].sort((a, b) => Number(b.pinned ?? false) - Number(a.pinned ?? false))
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

  /** 拖拽重排（补课 A5）：source 的 updatedAt 置于 target 之后（本地视觉排序）。 */
  function moveSessionAfter(sourceId: string, targetId: string): void {
    const src = sessions.value.find((s) => s.id === sourceId)
    const tgt = sessions.value.find((s) => s.id === targetId)
    if (!src || !tgt) return
    const tgtTs = tgt.updatedAt ? Date.parse(tgt.updatedAt) : Date.now()
    src.updatedAt = new Date(tgtTs + 1).toISOString()
  }

  function setSessionPinned(sessionId: string, pinned: boolean): void {
    const s = sessions.value.find((x) => x.id === sessionId)
    if (s) s.pinned = pinned
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
    // #10（台账 2026-09-11）：替换前回收旧数组持有的 blob URL，直设换入的
    // 客户端活消息不泄漏。现有调用方（useChat.switchSession）先 clearMessages
    // （已 revoke；revokeObjectURL 对已 revoke 的 URL 是规范 no-op，幂等）或
    // 传后端映射（无 blob URL），此回收对其无副作用。
    for (const m of messages.value) revokeMessageBlobUrls(m)
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
    // P1-10（审计 2026-09-11）：丢弃前回收每条消息持有的 blob URL
    // （audioUrl/ttsUrls/attachments[].preview），否则被弃消息的 Blob
    // 钉死内存直到整页刷新。
    for (const m of messages.value) revokeMessageBlobUrls(m)
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
      // P1-10：只回收被删轮次的 blob URL，保留消息不碰。
      revokeMessageBlobUrls(messages.value[i])
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

  // ── Token 用量 mutations（SSE usage 事件消费） ─────────────────────────

  function applyTurnUsage(sessionId: string | null, usage: { prompt: number; completion: number; total: number; estimated: boolean }): void {
    lastTurnUsage.value = {
      prompt: usage.prompt,
      completion: usage.completion,
      total: usage.total,
      estimated: usage.estimated,
    }
    if (!sessionId) return
    const acc = sessionTokenUsage.value[sessionId] ?? { prompt: 0, completion: 0, total: 0 }
    sessionTokenUsage.value[sessionId] = {
      prompt: acc.prompt + usage.prompt,
      completion: acc.completion + usage.completion,
      total: acc.total + usage.total,
    }
  }

  /** 会话累计用量读取（无记录返回 null）。 */
  function getSessionTokenUsage(sessionId: string | null): { prompt: number; completion: number; total: number } | null {
    if (!sessionId) return null
    return sessionTokenUsage.value[sessionId] ?? null
  }

  // ── 会话排序（拖拽落库后的本地同步） ──────────────────────────────────

  /** 按给定 id 顺序重排 sessions（reorder API 成功后本地同步，避免整表重拉）。 */
  function applySessionOrder(orderedIds: string[]): void {
    const rank = new Map(orderedIds.map((id, idx) => [id, idx]))
    sessions.value.sort((a, b) => (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER))
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
    // P1-10：同 clearMessages，弃置消息先回收 blob URL
    for (const m of messages.value) revokeMessageBlobUrls(m)
    messages.value = []
    isStreaming.value = false
    inputText.value = ''
    retrievalStatus.value = ''
    eventsLostBanner.value = null
    // P2-8（审计 2026-09-11）：per-session 用量累计一并清空——切 Agent 后
    // 旧 Agent 的用量残留会让环形用量图带出上一 Agent 数据，且 Record 只增不减
    sessionTokenUsage.value = {}
    lastTurnUsage.value = null
    // P2-19（审计 2026-09-11）：存档列表一并清空，旧 Agent 存档对象残留会串显
    archivedSessions.value = []
  }

  function setRetrievalStatus(status: string): void {
    retrievalStatus.value = status
  }
  function bumpEventsLost(count: number): void {
    eventsLostBanner.value = (eventsLostBanner.value ?? 0) + count
  }
  function clearEventsLost(): void {
    eventsLostBanner.value = null
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
    sessionTokenUsage,
    lastTurnUsage,
    retrievalStatus,
    eventsLostBanner,
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
    setSessionPinned,
    moveSessionAfter,
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
    setRetrievalStatus,
    bumpEventsLost,
    clearEventsLost,
    // usage
    applyTurnUsage,
    getSessionTokenUsage,
    applySessionOrder,
    // lifecycle
    reset,
  }
})

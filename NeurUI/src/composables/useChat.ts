import { ref } from 'vue'
import api from '@/api'
import { deleteConsoleSession } from '@/api/modules/console'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage, Session } from '@/types/chat'
import bus from '@/bus'

/**
 * useChat — composable that wires the chat store to backend session APIs.
 *
 * #2 / ADR 0008: Implements the user rule "建立统一的函数调用库,所有 UI 功能
 * 都必须通过这个库来调用,不能直接调用后端接口". All session CRUD flows through
 * this composable instead of being scattered across ChatPage.vue.
 *
 * Scope (current): session management (load/create/switch/delete/rename).
 * Out of scope (future composables): SSE streaming (useChatStreaming),
 * ASR (useASR), TTS (useTTS), file upload (useFileUpload).
 *
 * Events emitted on the unified bus:
 *   - chat:session-created   { sessionId, agentId }
 *   - chat:session-deleted   { sessionId }
 *   - chat:session-renamed   { sessionId, title }
 *   - chat:session-switched  { sessionId }
 */

export interface UseChatOptions {
  /** i18n error message resolver, e.g. (key, fallback) => t(key) || fallback */
  errorMessage?: (key: string, fallback: string) => string
  /** Optional message toast, e.g. uiMessage.error from ant-design-vue */
  onError?: (message: string) => void
}

export function useChat(options: UseChatOptions = {}) {
  const store = useChatStore()

  // Loading flags local to the composable (UI concerns, not domain state).
  const loadingSessions = ref<boolean>(false)
  const switchingSession = ref<boolean>(false)

  // ---------------------------------------------------------------------------
  // Session management
  // ---------------------------------------------------------------------------

  /**
   * Load the session list for the given agent. On success, auto-selects the
   * first session if none is currently active.
   */
  async function loadSessions(agentId: string): Promise<void> {
    loadingSessions.value = true
    try {
      const agentParam = agentId ? `?agent_id=${agentId}` : ''
      const res: any = await api.get(`/console/chat/sessions${agentParam}`)
      const data = res?.data ?? res
      const sessionList = data?.sessions ?? data ?? []
      const mapped: Session[] = sessionList.map(
        (s: any) => ({
          id: s.session_id || s.id,
          title: s.title || s.name || '新对话',
          updatedAt: s.created_at || s.updated_at,
        }),
      )
      store.setSessions(mapped)
      if (store.sessions.length > 0 && !store.currentSessionId) {
        await switchSession(store.sessions[0].id)
      }
    } catch {
      store.setSessions([])
    } finally {
      loadingSessions.value = false
    }
  }

  /**
   * Create a new session on the backend, then prepend it to the store and
   * switch to it. Uses the backend-returned session_id to avoid frontend/
   * backend id drift (see H-1 in docs/bugfix-history-load-bugs.md).
   */
  async function createSession(agentId: string, defaultTitle: string = '新对话'): Promise<string | null> {
    try {
      const res: any = await api.post('/console/chat/new')
      const data = res?.data ?? res
      const newId: string = data?.session_id || data?.id || crypto.randomUUID()
      const newSession: Session = {
        id: newId,
        title: `${defaultTitle} - ${new Date().toLocaleString()}`,
      }
      store.addSession(newSession)
      await switchSession(newId)
      bus.emit('chat:session-created', { sessionId: newId, agentId })
      return newId
    } catch (err) {
      console.error('[Chat] Create session failed:', err)
      const msg = options.errorMessage?.('chat.createSessionFailed', '创建会话失败') ?? '创建会话失败'
      options.onError?.(msg)
      return null
    }
  }

  /**
   * Switch to a session: set it as current, clear messages, and load its
   * history from the backend.
   */
  async function switchSession(sessionId: string): Promise<void> {
    store.setCurrentSession(sessionId)
    store.clearMessages()
    switchingSession.value = true
    try {
      const res: any = await api.get(`/console/chat/history?session_id=${sessionId}`)
      const data = res?.data ?? res
      const history = Array.isArray(data) ? data : data?.messages ?? data?.items ?? []
      const mapped: ChatMessage[] = history.map((m: any) => {
        // Build toolCalls array from tool_messages
        const toolCalls: Array<{ name: string; arguments: string; result?: string }> = []
        const toolMessages = m.tool_messages || []
        for (const tm of toolMessages) {
          if (tm.type === 'tool_call') {
            toolCalls.push({
              name: tm.tool_name || tm.name || '',
              arguments:
                typeof tm.params === 'string'
                  ? tm.params
                  : JSON.stringify(tm.params || tm.arguments || {}, null, 2),
            })
          } else if (tm.type === 'tool_result') {
            const resultText =
              typeof tm.result === 'string' ? tm.result : JSON.stringify(tm.result || '', null, 2)
            if (toolCalls.length > 0) {
              toolCalls[toolCalls.length - 1].result = resultText
            }
          }
        }
        // legacy single fallback
        const toolCall =
          toolCalls.length > 0
            ? toolCalls[0]
            : m.tool_call
              ? {
                  name: m.tool_call.name || m.tool_call.function?.name || '',
                  arguments: m.tool_call.arguments || m.tool_call.function?.arguments || '',
                }
              : undefined
        const toolResult = toolCalls.length > 0 ? toolCalls[0].result : m.tool_result || undefined
        return {
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content || '',
          reasoning: m.reasoning || m.reasoning_content || undefined,
          reasoningOpen: false,
          toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
          toolCall,
          toolResult,
        }
      })
      store.setMessages(mapped)
      bus.emit('chat:session-switched', { sessionId })
    } catch (err) {
      console.error('[Chat] Failed to load history:', err)
      const msg = options.errorMessage?.('chat.loadHistoryFailed', '加载历史对话失败') ?? '加载历史对话失败'
      options.onError?.(msg)
      store.clearMessages()
    } finally {
      switchingSession.value = false
    }
  }

  /**
   * Delete a session on the backend and update the store. If the deleted
   * session was active, switch to the first remaining session (or clear
   * current session if none remain).
   */
  async function deleteSession(sessionId: string): Promise<boolean> {
    try {
      await deleteConsoleSession(sessionId)
      store.removeSession(sessionId)
      if (store.currentSessionId === sessionId) {
        store.setCurrentSession(null)
        store.clearMessages()
        if (store.sessions.length > 0) {
          await switchSession(store.sessions[0].id)
        }
      }
      bus.emit('chat:session-deleted', { sessionId })
      return true
    } catch (err) {
      console.error('[Chat] Delete session failed:', err)
      return false
    }
  }

  /**
   * Rename a session: PUT the new title to the backend, then update the store.
   */
  async function renameSession(sessionId: string, title: string): Promise<boolean> {
    const trimmed = title.trim()
    if (!trimmed) return false
    try {
      await api.put(`/console/chat/sessions/${sessionId}`, { title: trimmed })
      store.renameSessionTitle(sessionId, trimmed)
      bus.emit('chat:session-renamed', { sessionId, title: trimmed })
      return true
    } catch (err) {
      console.error('[Chat] Rename failed:', err)
      const msg = options.errorMessage?.('chat.renameFailed', '重命名失败') ?? '重命名失败'
      options.onError?.(msg)
      return false
    }
  }

  return {
    // store passthrough (reactive)
    store,
    // loading flags
    loadingSessions,
    switchingSession,
    // session actions
    loadSessions,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
  }
}

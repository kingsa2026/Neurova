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

/**
 * switchSession 的执行结果类型.
 *
 * 架构契约: switchSession 不再内部决定错误策略 (是否弹 toast), 仅返回 ok/error.
 * 错误策略由调用方 own:
 *   - 副作用调用 (loadSessions 自动选第一个 / createSession 创建后切换 /
 *     deleteSession 删除后切换): 仅 console.error, 不弹 toast
 *   - 用户主动调用 (ChatPage.switchSession wrapper): 调 notifySwitchFailure
 *
 * 替换原 `silent: boolean` 浅参数模式 — 接口不再泄漏调用上下文, 决策空间
 * 留给调用方. 详见 docs/bugfix-delete-session-toast.md "架构深化" 小节.
 */
export type SwitchResult = { ok: true } | { ok: false; error: unknown }

/**
 * deleteSession 的执行结果类型.
 *
 * 架构契约: 与 SwitchResult 平行 — deleteSession 不再内部弹 toast, 仅返回
 * ok/error. 错误策略由调用方 own:
 *   - 副作用调用 (无): 无
 *   - 用户主动调用 (ChatPage.deleteSession wrapper): 调 notifyDeleteFailure
 *
 * 替换原 `Promise<boolean>` 浅返回模式 — 旧契约吞错 (catch 块 `return false`
 * 不调 onError) 导致 UI 无反馈 (chat.deleteSessionFailed bug).
 * 详见 docs/bugfix-delete-session-userid-mismatch.md "前端错误反馈策略深化" 小节.
 */
export type DeleteResult = { ok: true } | { ok: false; error: unknown }

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
        // 副作用调用: 自动选第一个 session. switchSession 返回失败结果但
        // loadSessions 静默消费 (不调 notifySwitchFailure), 避免页面加载时
        // auto-select 历史失败弹 toast 让用户误以为加载失败 (chat.loadHistoryFailed).
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
      const res: any = await api.post('/console/chat/new', { agent_id: agentId, title: defaultTitle })
      const data = res?.data ?? res
      // 幽灵 session 防御 (chat.loadHistoryFailed toast 根因修复):
      // 旧契约 fallback `|| crypto.randomUUID()` 会生成前端 UUID, 后端不知道,
      // 存到 store 后用户点击 GET /history → 404 → toast "加载历史对话失败".
      // 新契约: 后端不返回 session_id 时返回 null + 弹 toast, 不创建幽灵 session.
      // 详见 docs/bugfix-delete-session-userid-mismatch.md "幽灵 session 自愈".
      const newId: string | undefined = data?.session_id || data?.id
      if (!newId) {
        console.error('[Chat] Create session failed: backend response missing session_id', res)
        const msg = options.errorMessage?.('chat.createSessionFailed', '创建会话失败') ?? '创建会话失败'
        options.onError?.(msg)
        return null
      }
      const newSession: Session = {
        id: newId,
        title: defaultTitle,
      }
      store.addSession(newSession)
      // 副作用调用: 创建成功后自动切换. switchSession 返回失败结果但
      // createSession 静默消费 (不调 notifySwitchFailure), 因为创建已成功,
      // 历史加载失败不应掩盖创建结果.
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
   *
   * 契约: 本函数不弹 toast, 仅返回 SwitchResult. 错误策略 (是否提示用户)
   * 由调用方决定:
   *   - 副作用调用 (loadSessions/createSession/deleteSession 内部自动切换):
   *     仅消费 result, 不调 notifySwitchFailure → 静默
   *   - 用户主动调用 (ChatPage.switchSession wrapper 包装点击): 调
   *     notifySwitchFailure(result) → 失败时弹 toast
   *
   * 这是原 `silent: boolean` 浅参数模式的深化替代 — 接口不再泄漏调用
   * 上下文, 决策权交还调用方.
   */
  async function switchSession(sessionId: string): Promise<SwitchResult> {
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
      return { ok: true }
    } catch (err) {
      console.error('[Chat] Failed to load history:', err)
      store.clearMessages()
      // 幽灵 session 自愈 (chat.loadHistoryFailed toast 根因修复):
      // 404 表示后端不存在该 session (例如前端 UUID fallback 残留 / 后端
      // session 文件被删), 自动从 store 移除, 避免用户反复点击触发 toast.
      // 非 404 错误 (如 500 服务器故障 / 网络错误) 保留 session, 因为可能重试成功.
      // 详见 docs/bugfix-delete-session-userid-mismatch.md "幽灵 session 自愈".
      const status = (err as any)?.response?.status
      if (status === 404) {
        store.removeSession(sessionId)
        if (store.currentSessionId === sessionId) {
          store.setCurrentSession(null)
        }
      }
      return { ok: false, error: err }
    } finally {
      switchingSession.value = false
    }
  }

  /**
   * 用户主动切换场景的错误策略: 历史加载失败时弹 toast.
   *
   * 仅 ChatPage.switchSession wrapper (用户点击侧栏 session 项) 应调用此函数.
   * 副作用调用 (loadSessions/createSession/deleteSession 内部自动切换) 不调,
   * 避免让用户误以为主操作失败.
   */
  function notifySwitchFailure(result: SwitchResult): void {
    if (!result.ok) {
      const msg = options.errorMessage?.('chat.loadHistoryFailed', '加载历史对话失败') ?? '加载历史对话失败'
      options.onError?.(msg)
    }
  }

  /**
   * Delete a session on the backend and update the store. If the deleted
   * session was active, switch to the first remaining session (or clear
   * current session if none remain).
   *
   * 契约: 本函数不弹 toast, 仅返回 DeleteResult. 错误策略 (是否提示用户)
   * 由调用方决定:
   *   - 副作用调用 (无): 无
   *   - 用户主动调用 (ChatPage.deleteSession wrapper): 调 notifyDeleteFailure
   *
   * 这是原 `Promise<boolean>` 浅返回模式的深化替代 — 旧契约 catch 块
   * `return false` 吞错, 让 UI 无反馈 (chat.deleteSessionFailed bug).
   */
  async function deleteSession(sessionId: string): Promise<DeleteResult> {
    try {
      await deleteConsoleSession(sessionId)
      store.removeSession(sessionId)
      if (store.currentSessionId === sessionId) {
        store.setCurrentSession(null)
        store.clearMessages()
        if (store.sessions.length > 0) {
          // 副作用调用: 删除后自动切换. switchSession 不再 toast,
          // 失败结果由 deleteSession 静默消费 (不调 notifySwitchFailure),
          // 避免让用户误以为删除失败.
          await switchSession(store.sessions[0].id)
        }
      }
      bus.emit('chat:session-deleted', { sessionId })
      return { ok: true }
    } catch (err) {
      console.error('[Chat] Delete session failed:', err)
      return { ok: false, error: err }
    }
  }

  /**
   * 用户主动删除场景的错误策略: 删除失败时弹 toast.
   *
   * 仅 ChatPage.deleteSession wrapper (用户点击删除菜单项) 应调用此函数.
   * 副作用调用 (无) 不调, 避免误提示.
   *
   * 与 notifySwitchFailure 平行 — 错误策略集中, 调用方 own toast 决策.
   */
  function notifyDeleteFailure(result: DeleteResult): void {
    if (!result.ok) {
      const msg = options.errorMessage?.('chat.deleteSessionFailed', '删除会话失败') ?? '删除会话失败'
      options.onError?.(msg)
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
    // error policy helpers — 仅用户主动调用方调用 (ChatPage wrappers)
    notifySwitchFailure,
    notifyDeleteFailure,
  }
}

import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useAgentPage } from '@/composables/useAgentPage'
import { useChat } from '@/composables/useChat'
import { reorderConsoleSessions } from '@/api/modules/console'
import { uiMessage } from '@/utils/message'
import { resolveI18nMessage } from '@/utils/i18n'
import type { Session } from '@/types/chat'

/**
 * 会话操作共享层（2026-09-08 dock 收编 + ChatPage 拆分产物）。
 *
 * 会话分组/拖拽重排/置顶/存档/恢复/重命名等 UI 包装从 ChatPage 迁出，
 * 供左侧会话侧栏与 dock 历史/存档 tab 共用；switchSession 因与流式
 * 状态机（abort/草稿恢复/滚动锚定）耦合，保留在页面编排层，由模板 emit 上抛。
 *
 * renameModal 为模块级共享 reactive（重命名弹窗独立组件与触发方零 props 连线）。
 */

export interface SessionGroup {
  key: string
  label: string
  sessions: Session[]
}

/** 模块级共享：重命名弹窗状态（跨组件单例） */
const renameModal = reactive({ open: false, sessionId: '', title: '' })

export function useSessionOps() {
  const chatStore = useChatStore()
  const { t } = useI18n()
  const { agentId } = useAgentPage()
  const { sessions, filteredSessions } = storeToRefs(chatStore)

  const {
    renameSession: _renameSession,
    deleteSession: _deleteSession,
    pinSession: _pinSession,
    archiveSession: _archiveSession,
    loadArchivedSessions: _loadArchivedSessions,
    restoreSession: _restoreSession,
    notifyDeleteFailure: _notifyDeleteFailure,
  } = useChat({
    errorMessage: (key, fallback) => resolveI18nMessage(t, key, fallback),
    onError: (msg) => uiMessage.error(msg),
  })

  // ── 会话分组（置顶 / 今天 / 本周 / 更早）───────────────────────
  const dragOverSessionId = ref<string | null>(null)
  const draggingSessionId = ref<string | null>(null)

  const groupedSessions = computed<SessionGroup[]>(() => {
    const pinned = filteredSessions.value.filter((s) => s.pinned)
    const rest = filteredSessions.value.filter((s) => !s.pinned)
    const now = Date.now()
    const DAY = 86_400_000
    const buckets: Record<string, Session[]> = { today: [], week: [], earlier: [] }
    for (const s of rest) {
      const ts = s.updatedAt ? Date.parse(s.updatedAt) : NaN
      if (Number.isNaN(ts)) buckets.today.push(s)
      else if (now - ts < DAY) buckets.today.push(s)
      else if (now - ts < 7 * DAY) buckets.week.push(s)
      else buckets.earlier.push(s)
    }
    const groups: SessionGroup[] = []
    if (pinned.length) groups.push({ key: 'pinned', label: t('chat.groupPinned'), sessions: pinned })
    if (buckets.today.length) groups.push({ key: 'today', label: t('chat.groupToday'), sessions: buckets.today })
    if (buckets.week.length) groups.push({ key: 'week', label: t('chat.groupWeek'), sessions: buckets.week })
    if (buckets.earlier.length) groups.push({ key: 'earlier', label: t('chat.groupEarlier'), sessions: buckets.earlier })
    return groups
  })

  function onSessionDragStart(sessionId: string, e: DragEvent): void {
    draggingSessionId.value = sessionId
    e.dataTransfer?.setData('text/plain', sessionId)
  }

  /** 拖拽放下 = 把拖拽会话的 updatedAt 移到目标之后（重排=本地排序，QP 同款语义）。 */
  function onSessionDrop(targetId: string): void {
    const sourceId = draggingSessionId.value
    draggingSessionId.value = null
    dragOverSessionId.value = null
    if (!sourceId || sourceId === targetId) return
    chatStore.moveSessionAfter(sourceId, targetId)
    // 拖拽排序落库（QwenPaw /chats/groups/order 对齐）：本地视觉排序立即生效，
    // 同时异步持久化 sort_order（失败静默——本地排序仍可用，刷新后回退服务端顺序）。
    void persistSessionOrder()
  }

  /** 把当前会话顺序（含置顶区顺序）整体落库。 */
  async function persistSessionOrder(): Promise<void> {
    if (!agentId.value) return
    const orderedIds = filteredSessions.value.map((s) => s.id).filter(Boolean)
    if (orderedIds.length === 0) return
    try {
      await reorderConsoleSessions(agentId.value, orderedIds)
      chatStore.applySessionOrder(orderedIds)
    } catch (e) {
      console.warn('[useSessionOps] persist session order failed:', e)
    }
  }

  /**
   * 新对话（2026-09-08 bug1：空会话不落库）。
   * 不再立即 POST /chat/new 落库空会话——改为本地"预备态"：
   * 清空消息区与会话选中，composer 输入后 sendMessage 走既有链路
   * （body.session_id 为空 → 后端自动 create_session），首次发送即建会话。
   * 用户取消不输入 = 零落库。
   */
  function createSession(): void {
    chatStore.clearMessages()
    chatStore.setCurrentSession(null)
    chatStore.setInputText('')
  }

  /** 打开重命名 modal（只读 sessions，不调 API）。 */
  function renameSession(sessionId: string): void {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (!session) return
    renameModal.sessionId = sessionId
    renameModal.title = session.title
    renameModal.open = true
  }

  /** 确认重命名（modal @ok），委托 useChat.renameSession。 */
  async function confirmRename(): Promise<void> {
    if (!renameModal.title.trim()) return
    const ok = await _renameSession(renameModal.sessionId, renameModal.title.trim())
    if (ok) renameModal.open = false
  }

  /** 删除会话；失败弹 toast（与原 ChatPage wrapper 一致）。 */
  async function deleteSession(sessionId: string): Promise<void> {
    const result = await _deleteSession(sessionId)
    _notifyDeleteFailure(result)
  }

  /** 置顶/取消置顶（静默失败不打断列表交互）。 */
  async function togglePin(session: Session): Promise<void> {
    const ok = await _pinSession(session.id, !session.pinned)
    if (!ok) {
      uiMessage.error(resolveI18nMessage(t, 'chat.pinFailed', t('chat.pinFailed')))
    }
  }

  /** 存档会话，失败弹 toast。 */
  async function archiveSession(sessionId: string): Promise<void> {
    const result = await _archiveSession(sessionId)
    if (!result.ok) {
      uiMessage.error(resolveI18nMessage(t, 'chat.archiveFailed', t('chat.archiveFailed')))
    }
  }

  /** 加载存档列表（dock 存档 tab 打开时调用）。 */
  async function loadArchivedSessions(): Promise<void> {
    await _loadArchivedSessions(agentId.value)
  }

  /** 恢复存档会话为正常会话。 */
  async function restoreArchivedSession(sessionId: string): Promise<void> {
    const result = await _restoreSession(sessionId)
    if (!result.ok) {
      uiMessage.error(resolveI18nMessage(t, 'chat.restoreFailed', t('chat.restoreFailed')))
    }
  }

  return {
    renameModal,
    groupedSessions,
    dragOverSessionId,
    dragOver: dragOverSessionId,
    onSessionDragStart,
    onSessionDrop,
    createSession,
    renameSession,
    confirmRename,
    deleteSession,
    togglePin,
    archiveSession,
    loadArchivedSessions,
    restoreArchivedSession,
  }
}

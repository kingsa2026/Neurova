/**
 * collaboration.ts — 协作模块 Pinia store
 *
 * 集中管理协作域跨页面共享状态：sessions / templates / history / stats / canvas
 * 所有 API 调用与错误处理通过此 store 收口，页面不直接调用 api 模块。
 *
 * 模式参考：stores/agents.ts（defineStore + setup 语法）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listSessions, listTemplates, listHistory, startSession,
  createTemplate, updateTemplate, deleteTemplate,
  getCollabStats, saveCanvas, runCanvas, getCanvas, updateCanvas,
  type CollabSession, type CollabTemplate, type CollabStats,
  type CanvasSnapshot, type StartSessionPayload, type CreateTemplatePayload, type SaveCanvasPayload,
} from '@/api/modules/collaboration'
import { handleError } from '@/utils/error'
import { logger } from '@/utils/logger'

export const useCollaborationStore = defineStore('collaboration', () => {
  // ── State ──
  const sessions = ref<CollabSession[]>([])
  const templates = ref<CollabTemplate[]>([])
  const history = ref<CollabSession[]>([])
  const stats = ref<CollabStats | null>(null)
  const currentCanvas = ref<CanvasSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── Getters ──
  const activeSessions = computed(() => sessions.value.filter(s => s.status === 'active'))
  const completedSessions = computed(() => sessions.value.filter(s => s.status === 'completed'))
  const sessionCount = computed(() => sessions.value.length)

  // ── Actions ──
  // 兼容两种后端包裹形态：data 直接为数组，或 data: { history/sessions: [...] } 对象。
  // 修复：/history 返回 {history:[...], total} 时被整体赋给数组 ref，
  // 导致页面 history.value.slice is not a function 崩溃。
  function asArray<T>(payload: unknown, keys: string[] = []): T[] {
    const p = payload as any
    if (Array.isArray(p)) return p as T[]
    for (const k of keys) {
      if (Array.isArray(p?.[k])) return p[k] as T[]
    }
    return []
  }

  async function fetchSessions() {
    loading.value = true
    try {
      const res = await listSessions()
      sessions.value = asArray<CollabSession>((res as any)?.data ?? res, ['sessions'])
    } catch (e) {
      error.value = (e as Error).message
      handleError(e, 'fetchSessions')
      sessions.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchTemplates() {
    loading.value = true
    try {
      const res = await listTemplates()
      templates.value = asArray<CollabTemplate>((res as any)?.data ?? res, ['templates'])
    } catch (e) {
      error.value = (e as Error).message
      handleError(e, 'fetchTemplates')
      templates.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchHistory() {
    loading.value = true
    try {
      const res = await listHistory()
      history.value = asArray<CollabSession>((res as any)?.data ?? res, ['history'])
    } catch (e) {
      error.value = (e as Error).message
      handleError(e, 'fetchHistory')
      history.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const res = await getCollabStats()
      stats.value = ((res as any)?.data ?? res) as CollabStats
    } catch (e) {
      handleError(e, 'fetchStats')
      logger.warn('fetchStats failed', e)
    }
  }

  async function startSessionAction(payload: StartSessionPayload) {
    loading.value = true
    try {
      await startSession(payload)
      await fetchSessions()
      await fetchStats()
    } catch (e) {
      error.value = (e as Error).message
      handleError(e, 'startSession')
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createTemplateAction(payload: CreateTemplatePayload) {
    try {
      await createTemplate(payload)
      await fetchTemplates()
    } catch (e) {
      handleError(e, 'createTemplate')
      throw e
    }
  }

  async function updateTemplateAction(id: string, payload: CreateTemplatePayload) {
    try {
      await updateTemplate(id, payload)
      await fetchTemplates()
    } catch (e) {
      handleError(e, 'updateTemplate')
      throw e
    }
  }

  async function deleteTemplateAction(id: string) {
    try {
      await deleteTemplate(id)
      await fetchTemplates()
    } catch (e) {
      handleError(e, 'deleteTemplate')
      throw e
    }
  }

  async function saveCanvasAction(payload: SaveCanvasPayload, baseVersion?: number) {
    loading.value = true
    try {
      const res = await (payload.id
        ? updateCanvas(payload.id, payload, baseVersion)
        : saveCanvas(payload))
      currentCanvas.value = ((res as any)?.data ?? res) as CanvasSnapshot
      return currentCanvas.value
    } catch (e) {
      handleError(e, 'saveCanvas')
      throw e
    } finally {
      loading.value = false
    }
  }

  async function runCanvasAction(canvasId: string) {
    try {
      return await runCanvas(canvasId)
    } catch (e) {
      handleError(e, 'runCanvas')
      throw e
    }
  }

  async function fetchCanvas(canvasId: string) {
    loading.value = true
    try {
      const res = await getCanvas(canvasId)
      currentCanvas.value = ((res as any)?.data ?? res) as CanvasSnapshot
      return currentCanvas.value
    } catch (e) {
      handleError(e, 'fetchCanvas')
      throw e
    } finally {
      loading.value = false
    }
  }

  function $reset() {
    sessions.value = []
    templates.value = []
    history.value = []
    stats.value = null
    currentCanvas.value = null
    loading.value = false
    error.value = null
  }

  return {
    // state
    sessions, templates, history, stats, currentCanvas, loading, error,
    // getters
    activeSessions, completedSessions, sessionCount,
    // actions
    fetchSessions, fetchTemplates, fetchHistory, fetchStats,
    startSessionAction, createTemplateAction, updateTemplateAction, deleteTemplateAction,
    saveCanvasAction, runCanvasAction, fetchCanvas,
    $reset,
  }
})

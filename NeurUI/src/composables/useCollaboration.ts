/**
 * useCollaboration.ts — 协作模块 composable
 *
 * 封装 useCollaborationStore + uiMessage，作为页面调用协作域功能的统一入口。
 * 页面不直接调用 store 或 api，全部通过此 composable。
 *
 * 模式参考：composables/useAPI.ts
 */
import { storeToRefs } from 'pinia'
import { useCollaborationStore } from '@/stores/collaboration'
import { uiMessage } from '@/utils/message'
import { useI18n } from 'vue-i18n'
import type {
  StartSessionPayload,
  CreateTemplatePayload,
  SaveCanvasPayload,
  CanvasSnapshot,
  CanvasSummary,
} from '@/api/modules/collaboration'
import { listCanvases as listCanvasesApi } from '@/api/modules/collaboration'

/** 画布保存版本冲突（409）：服务端已被其他编辑者（如 agent）更新。
 *  页面应重载最新快照后让用户重试，而不是静默覆盖。 */
export class CanvasVersionConflictError extends Error {
  currentVersion: number | null
  constructor(currentVersion: number | null, message = 'canvas version conflict') {
    super(message)
    this.name = 'CanvasVersionConflictError'
    this.currentVersion = currentVersion
  }
}

/** 判断 axios 错误是否为画布版本冲突 409 */
function asVersionConflict(e: unknown): CanvasVersionConflictError | null {
  const resp = (e as any)?.response
  if (resp?.status !== 409) return null
  const detail = resp.data?.detail
  const current =
    typeof detail?.current_version === 'number' ? detail.current_version : null
  return new CanvasVersionConflictError(current, typeof detail?.error === 'string' ? detail.error : undefined)
}

export function useCollaboration() {
  const store = useCollaborationStore()
  const { t } = useI18n()
  const refs = storeToRefs(store)

  async function loadSessions() {
    await store.fetchSessions()
  }

  async function loadTemplates() {
    await store.fetchTemplates()
  }

  async function loadHistory() {
    await store.fetchHistory()
  }

  async function loadStats() {
    await store.fetchStats()
  }

  async function startSession(payload: StartSessionPayload): Promise<boolean> {
    try {
      await store.startSessionAction(payload)
      uiMessage.success(t('common.success'))
      return true
    } catch {
      uiMessage.error(t('common.error'))
      return false
    }
  }

  async function saveTemplate(payload: CreateTemplatePayload, id?: string): Promise<boolean> {
    try {
      if (id) {
        await store.updateTemplateAction(id, payload)
      } else {
        await store.createTemplateAction(payload)
      }
      uiMessage.success(t('common.success'))
      return true
    } catch {
      uiMessage.error(t('common.error'))
      return false
    }
  }

  async function removeTemplate(id: string): Promise<boolean> {
    try {
      await store.deleteTemplateAction(id)
      uiMessage.success(t('common.success'))
      return true
    } catch {
      uiMessage.error(t('common.error'))
      return false
    }
  }

  async function saveCanvas(
    payload: SaveCanvasPayload,
    baseVersion?: number,
  ): Promise<CanvasSnapshot | null> {
    try {
      const saved = await store.saveCanvasAction(payload, baseVersion)
      uiMessage.success(t('common.success'))
      return saved
    } catch (e) {
      const conflict = asVersionConflict(e)
      if (conflict) throw conflict // 版本冲突交给页面处理（重载+提示）
      uiMessage.error(t('common.error'))
      return null
    }
  }

  async function runCanvas(canvasId: string): Promise<boolean> {
    try {
      await store.runCanvasAction(canvasId)
      uiMessage.success(t('workflow.execute') + ' ' + t('common.success'))
      return true
    } catch {
      uiMessage.error(t('common.error'))
      return false
    }
  }

  async function loadCanvas(canvasId: string): Promise<CanvasSnapshot | null> {
    try {
      return await store.fetchCanvas(canvasId)
    } catch {
      return null
    }
  }

  /** 已保存画布摘要列表（"我的画布"）；失败返回空数组不打断页面 */
  async function listSavedCanvases(): Promise<CanvasSummary[]> {
    try {
      const res = await listCanvasesApi()
      return (((res as any)?.data ?? res) as CanvasSummary[]) || []
    } catch {
      return []
    }
  }

  return {
    ...refs,
    loadSessions,
    loadTemplates,
    loadHistory,
    loadStats,
    startSession,
    saveTemplate,
    removeTemplate,
    saveCanvas,
    runCanvas,
    loadCanvas,
    listSavedCanvases,
    $reset: store.$reset,
  }
}

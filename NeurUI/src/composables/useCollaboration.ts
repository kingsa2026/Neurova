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
} from '@/api/modules/collaboration'

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

  async function saveCanvas(payload: SaveCanvasPayload): Promise<CanvasSnapshot | null> {
    try {
      const saved = await store.saveCanvasAction(payload)
      uiMessage.success(t('common.success'))
      return saved
    } catch {
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
    $reset: store.$reset,
  }
}

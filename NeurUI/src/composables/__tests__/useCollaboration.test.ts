/**
 * useCollaboration.test.ts — Phase B RED: useCollaboration composable 单元测试
 *
 * 验证 composable 封装：返回 store refs + 调用 uiMessage 反馈
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock api/modules/collaboration
vi.mock('@/api/modules/collaboration', () => ({
  listSessions: vi.fn(),
  listTemplates: vi.fn(),
  listHistory: vi.fn(),
  startSession: vi.fn(),
  createTemplate: vi.fn(),
  updateTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  getCollabStats: vi.fn(),
  saveCanvas: vi.fn(),
  runCanvas: vi.fn(),
  getCanvas: vi.fn(),
  updateCanvas: vi.fn(),
}))

// Mock utils/error 与 utils/logger
vi.mock('@/utils/error', () => ({ handleError: vi.fn() }))
vi.mock('@/utils/logger', () => ({ logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() } }))

// Mock utils/message — 使用 vi.hoisted 避免 hoisting 引用问题
const { mockSuccess, mockError } = vi.hoisted(() => ({
  mockSuccess: vi.fn(),
  mockError: vi.fn(),
}))
vi.mock('@/utils/message', () => ({
  uiMessage: {
    success: mockSuccess,
    error: mockError,
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

// Mock vue-i18n — t 返回 key 本身便于断言
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import { useCollaboration } from '@/composables/useCollaboration'
import * as collabApi from '@/api/modules/collaboration'

describe('useCollaboration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // ── Test 1: 返回 store refs + actions ──
  it('returns store refs and actions', () => {
    const collab = useCollaboration()
    // refs
    expect(collab.sessions).toBeDefined()
    expect(collab.templates).toBeDefined()
    expect(collab.history).toBeDefined()
    expect(collab.stats).toBeDefined()
    expect(collab.loading).toBeDefined()
    // actions
    expect(typeof collab.loadSessions).toBe('function')
    expect(typeof collab.loadTemplates).toBe('function')
    expect(typeof collab.startSession).toBe('function')
    expect(typeof collab.saveTemplate).toBe('function')
    expect(typeof collab.removeTemplate).toBe('function')
    expect(typeof collab.saveCanvas).toBe('function')
    expect(typeof collab.runCanvas).toBe('function')
    expect(typeof collab.loadCanvas).toBe('function')
  })

  // ── Test 2: startSession 成功显示 uiMessage.success ──
  it('startSession shows success message on success', async () => {
    ;(collabApi.startSession as any).mockResolvedValue({ data: {} })
    ;(collabApi.listSessions as any).mockResolvedValue({ data: [] })
    ;(collabApi.getCollabStats as any).mockResolvedValue({ data: {} })

    const collab = useCollaboration()
    const ok = await collab.startSession({
      templateId: 't1', participants: ['u1'], name: 'S', description: '',
    })

    expect(ok).toBe(true)
    expect(mockSuccess).toHaveBeenCalledWith('common.success')
    expect(mockError).not.toHaveBeenCalled()
  })

  // ── Test 3: startSession 失败显示 uiMessage.error 并返回 false ──
  it('startSession shows error message and returns false on failure', async () => {
    ;(collabApi.startSession as any).mockRejectedValue(new Error('fail'))

    const collab = useCollaboration()
    const ok = await collab.startSession({
      templateId: 't1', participants: [], name: '', description: '',
    })

    expect(ok).toBe(false)
    expect(mockError).toHaveBeenCalledWith('common.error')
  })

  // ── Test 4: saveTemplate 无 id 调用 createTemplateAction ──
  it('saveTemplate without id calls createTemplateAction', async () => {
    ;(collabApi.createTemplate as any).mockResolvedValue({ data: {} })
    ;(collabApi.listTemplates as any).mockResolvedValue({ data: [] })

    const collab = useCollaboration()
    const ok = await collab.saveTemplate({ name: 'T', description: '', type: 'pipeline' })

    expect(ok).toBe(true)
    expect(collabApi.createTemplate).toHaveBeenCalledOnce()
    expect(collabApi.updateTemplate).not.toHaveBeenCalled()
  })

  // ── Test 5: saveTemplate 有 id 调用 updateTemplateAction ──
  it('saveTemplate with id calls updateTemplateAction', async () => {
    ;(collabApi.updateTemplate as any).mockResolvedValue({ data: {} })
    ;(collabApi.listTemplates as any).mockResolvedValue({ data: [] })

    const collab = useCollaboration()
    const ok = await collab.saveTemplate({ name: 'T', description: '', type: 'pipeline' }, 'tpl-123')

    expect(ok).toBe(true)
    expect(collabApi.updateTemplate).toHaveBeenCalledOnce()
    expect(collabApi.createTemplate).not.toHaveBeenCalled()
  })

  // ── Test 6: saveCanvas 成功返回 saved snapshot ──
  it('saveCanvas returns saved snapshot on success', async () => {
    const saved = { id: 'c1', name: 'Canvas', nodes: [], edges: [] }
    ;(collabApi.saveCanvas as any).mockResolvedValue({ data: saved })

    const collab = useCollaboration()
    const result = await collab.saveCanvas({ name: 'Canvas', nodes: [], edges: [] })

    expect(result).toEqual(saved)
    expect(mockSuccess).toHaveBeenCalledWith('common.success')
  })
})

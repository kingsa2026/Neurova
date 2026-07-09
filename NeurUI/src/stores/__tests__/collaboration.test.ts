/**
 * collaboration.test.ts — Phase A RED: useCollaborationStore 单元测试
 *
 * TDD 红绿灯：先写测试，验证 store 接口契约
 * 测试覆盖：state 初始化、fetch actions、getters、$reset
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock api/modules/collaboration — 必须在 import store 之前
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

// Mock utils/error 与 utils/logger 避免副作用
vi.mock('@/utils/error', () => ({
  handleError: vi.fn(),
}))
vi.mock('@/utils/logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}))

import { useCollaborationStore } from '@/stores/collaboration'
import * as collabApi from '@/api/modules/collaboration'

describe('useCollaborationStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // ── Test 1: 初始化 state 为空 ──
  it('initializes with empty state', () => {
    const store = useCollaborationStore()
    expect(store.sessions).toEqual([])
    expect(store.templates).toEqual([])
    expect(store.history).toEqual([])
    expect(store.stats).toBe(null)
    expect(store.currentCanvas).toBe(null)
    expect(store.loading).toBe(false)
    expect(store.error).toBe(null)
  })

  // ── Test 2: fetchSessions 成功填充 sessions ──
  it('fetchSessions fills sessions on success', async () => {
    const mockSessions = [
      { id: 's1', name: 'Session 1', description: '', status: 'active', createdAt: '2024-01-01' },
      { id: 's2', name: 'Session 2', description: '', status: 'completed', createdAt: '2024-01-02' },
    ]
    ;(collabApi.listSessions as any).mockResolvedValue({ data: mockSessions })

    const store = useCollaborationStore()
    await store.fetchSessions()

    expect(collabApi.listSessions).toHaveBeenCalledOnce()
    expect(store.sessions).toEqual(mockSessions)
    expect(store.loading).toBe(false)
    expect(store.error).toBe(null)
  })

  // ── Test 3: fetchSessions 失败设置 error 并清空 sessions ──
  it('fetchSessions sets error and clears sessions on failure', async () => {
    ;(collabApi.listSessions as any).mockRejectedValue(new Error('network error'))

    const store = useCollaborationStore()
    store.sessions = [{ id: 'old', name: 'old', description: '', status: 'active', createdAt: '' }]
    await store.fetchSessions()

    expect(store.sessions).toEqual([])
    expect(store.error).toBe('network error')
    expect(store.loading).toBe(false)
  })

  // ── Test 4: fetchTemplates 成功填充 templates ──
  it('fetchTemplates fills templates on success', async () => {
    const mockTemplates = [
      { id: 't1', name: 'Template 1', description: '', type: 'pipeline' },
    ]
    ;(collabApi.listTemplates as any).mockResolvedValue({ data: mockTemplates })

    const store = useCollaborationStore()
    await store.fetchTemplates()

    expect(collabApi.listTemplates).toHaveBeenCalledOnce()
    expect(store.templates).toEqual(mockTemplates)
  })

  // ── Test 5: startSessionAction 成功后调用 fetchSessions + fetchStats ──
  it('startSessionAction refreshes sessions and stats on success', async () => {
    ;(collabApi.startSession as any).mockResolvedValue({ data: {} })
    ;(collabApi.listSessions as any).mockResolvedValue({ data: [] })
    ;(collabApi.getCollabStats as any).mockResolvedValue({ data: { sessions: 1, templates: 0, workflows: 0, projects: 0 } })

    const store = useCollaborationStore()
    await store.startSessionAction({
      templateId: 't1', participants: ['u1'], name: 'Test', description: '',
    })

    // startSession 被调用，且内部触发了 fetchSessions（listSessions）+ fetchStats（getCollabStats）
    expect(collabApi.startSession).toHaveBeenCalledOnce()
    expect(collabApi.listSessions).toHaveBeenCalled()
    expect(collabApi.getCollabStats).toHaveBeenCalled()
    expect(store.loading).toBe(false)
  })

  // ── Test 6: saveCanvasAction 无 id 时调用 saveCanvas ──
  it('saveCanvasAction calls saveCanvas when no id', async () => {
    const saved = { id: 'c1', name: 'New Canvas', nodes: [], edges: [] }
    ;(collabApi.saveCanvas as any).mockResolvedValue({ data: saved })

    const store = useCollaborationStore()
    const result = await store.saveCanvasAction({ name: 'New Canvas', nodes: [], edges: [] })

    expect(collabApi.saveCanvas).toHaveBeenCalledOnce()
    expect(collabApi.updateCanvas).not.toHaveBeenCalled()
    expect(store.currentCanvas).toEqual(saved)
    expect(result).toEqual(saved)
  })

  // ── Test 7: saveCanvasAction 有 id 时调用 updateCanvas ──
  it('saveCanvasAction calls updateCanvas when id present', async () => {
    const updated = { id: 'c1', name: 'Updated', nodes: [], edges: [] }
    ;(collabApi.updateCanvas as any).mockResolvedValue({ data: updated })

    const store = useCollaborationStore()
    const result = await store.saveCanvasAction({ id: 'c1', name: 'Updated', nodes: [], edges: [] })

    expect(collabApi.updateCanvas).toHaveBeenCalledOnce()
    expect(collabApi.saveCanvas).not.toHaveBeenCalled()
    expect(result).toEqual(updated)
  })

  // ── Test 8: activeSessions getter 过滤 status=active ──
  it('activeSessions getter filters status=active', () => {
    const store = useCollaborationStore()
    store.sessions = [
      { id: 's1', name: 'Active', description: '', status: 'active', createdAt: '' },
      { id: 's2', name: 'Completed', description: '', status: 'completed', createdAt: '' },
      { id: 's3', name: 'Active 2', description: '', status: 'active', createdAt: '' },
    ] as any

    expect(store.activeSessions).toHaveLength(2)
    expect(store.activeSessions.map(s => s.id)).toEqual(['s1', 's3'])
    expect(store.completedSessions).toHaveLength(1)
    expect(store.sessionCount).toBe(3)
  })

  // ── Test 9: $reset 清空所有 state ──
  it('$reset clears all state', () => {
    const store = useCollaborationStore()
    store.sessions = [{ id: 's1', name: 's', description: '', status: 'active', createdAt: '' }] as any
    store.templates = [{ id: 't1', name: 't', description: '', type: 'pipeline' }] as any
    store.history = [{ id: 'h1', name: 'h', description: '', status: 'completed', createdAt: '' }] as any
    store.stats = { sessions: 1, templates: 1, workflows: 0, projects: 0 }
    store.currentCanvas = { name: 'c', nodes: [], edges: [] } as any
    store.loading = true
    store.error = 'some error'

    store.$reset()

    expect(store.sessions).toEqual([])
    expect(store.templates).toEqual([])
    expect(store.history).toEqual([])
    expect(store.stats).toBe(null)
    expect(store.currentCanvas).toBe(null)
    expect(store.loading).toBe(false)
    expect(store.error).toBe(null)
  })
})

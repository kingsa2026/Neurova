/**
 * agents.test.ts — Agent 下拉回归测试
 *
 * 回归背景：画布 builtin:agent 节点的「执行 Agent」下拉，
 * 选项来自 useAgentStore().agentOptions（GET /agents）。
 * 本测试锁定 store 契约：loadAgents 归一化响应、agentOptions 映射为 {label,value}。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock api 客户端（store 直接 import { api } from '@/api'）
vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { useAgentStore } from '@/stores/agents'
import { api } from '@/api'

const mockedGet = vi.mocked(api.get)

describe('useAgentStore — agentOptions（画布 Agent 下拉数据源）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadAgents 从 GET /agents 归一化并映射 agentOptions 为 {label, value}', async () => {
    mockedGet.mockResolvedValueOnce({
      data: [
        { id: 'agent-1', name: '研究员', status: 'active' },
        { id: 'agent-2', name: '写作者', status: 'active' },
      ],
    })

    const store = useAgentStore()
    await store.loadAgents()

    expect(mockedGet).toHaveBeenCalledWith('/agents')
    expect(store.agents).toHaveLength(2)
    expect(store.agentOptions).toEqual([
      { label: '研究员', value: 'agent-1', isWorkflow: false },
      { label: '写作者', value: 'agent-2', isWorkflow: false },
    ])
  })

  it('兼容 {items:[...]} 与裸数组两种响应形状', async () => {
    mockedGet.mockResolvedValueOnce({ items: [{ id: 'a', name: 'A' }] })
    const store = useAgentStore()
    await store.loadAgents()
    expect(store.agentOptions).toEqual([{ label: 'A', value: 'a', isWorkflow: false }])

    mockedGet.mockResolvedValueOnce([{ id: 'b', name: 'B' }])
    await store.loadAgents()
    expect(store.agentOptions).toEqual([{ label: 'B', value: 'b', isWorkflow: false }])
  })

  it('加载失败时 agentOptions 为空数组且不抛异常', async () => {
    mockedGet.mockRejectedValueOnce(new Error('network down'))
    const store = useAgentStore()
    await expect(store.loadAgents()).resolves.toBeUndefined()
    expect(store.agentOptions).toEqual([])
    expect(store.error).toContain('network down')
  })
})

describe('useAgentStore — workflow agents 合并（遗留③b）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadWorkflowAgents 从 /neurflow/agents 拉取并合并进 agentOptions（isWorkflow 标记）', async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url === '/agents') {
        return Promise.resolve({ data: [{ id: 'agent-1', name: '研究员', status: 'active' }] })
      }
      if (url === '/neurflow/agents') {
        return Promise.resolve({
          data: {
            agents: [
              {
                agent_id: 'wf_agent_wf_pub',
                name: '发布测试',
                role: 'workflow-triggered agent',
                capabilities: ['workflow'],
                metadata: { source_type: 'workflow', workflow_id: 'wf_pub' },
                status: 'active',
              },
            ],
            total: 1,
          },
        })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })

    const store = useAgentStore()
    await store.loadAgents()
    await store.loadWorkflowAgents()

    expect(store.agentOptions).toEqual([
      { label: '研究员', value: 'agent-1', isWorkflow: false },
      { label: '发布测试', value: 'wf_agent_wf_pub', isWorkflow: true },
    ])
  })

  it('loadWorkflowAgents 过滤非 workflow source 的记录且失败静默', async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url === '/agents') return Promise.resolve({ data: [] })
      if (url === '/neurflow/agents') {
        return Promise.resolve({
          data: {
            agents: [
              { agent_id: 'manual1', name: '普通', metadata: {}, status: 'active' },
              { agent_id: 'wf_agent_w1', name: '工作流A', metadata: { source_type: 'workflow', workflow_id: 'w1' }, status: 'active' },
            ],
            total: 2,
          },
        })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })

    const store = useAgentStore()
    await store.loadAgents()
    await store.loadWorkflowAgents()
    expect(store.agentOptions).toEqual([
      { label: '工作流A', value: 'wf_agent_w1', isWorkflow: true },
    ])

    // 失败静默
    mockedGet.mockRejectedValueOnce(new Error('down'))
    await expect(store.loadWorkflowAgents()).resolves.toBeUndefined()
  })
})

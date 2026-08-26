import { describe, it, expect } from 'vitest'
import { extractWorkflowList } from '../workflowList'
import type { WorkflowDefinition } from '@/api/modules/neurflow'

const wf = (id: string): WorkflowDefinition =>
  ({
    id,
    name: `flow-${id}`,
    description: '',
    version: '1.0.0',
    nodes: [],
    edges: [],
    variables: [],
    tags: [],
    category: 'general',
    author: '',
    created_at: 0,
    updated_at: 0,
    status: 'draft',
    template: false,
    public: false,
    metadata: {},
  }) as WorkflowDefinition

describe('extractWorkflowList', () => {
  it('从 ApiResponse 包装 { data: { workflows: [...] } } 中提取列表（后端实际返回形状）', () => {
    const res = { code: 0, message: 'success', data: { workflows: [wf('a'), wf('b')], total: 2 } }
    expect(extractWorkflowList(res).map((w) => w.id)).toEqual(['a', 'b'])
  })

  it('从裸 { workflows: [...] } 中提取列表', () => {
    const res = { workflows: [wf('c')], total: 1 }
    expect(extractWorkflowList(res).map((w) => w.id)).toEqual(['c'])
  })

  it('透传纯数组', () => {
    expect(extractWorkflowList([wf('d')]).map((w) => w.id)).toEqual(['d'])
  })

  it('从 { data: [...] } 中提取列表', () => {
    const res = { code: 0, data: [wf('e')] }
    expect(extractWorkflowList(res).map((w) => w.id)).toEqual(['e'])
  })

  it('无法识别的形状返回空数组而不是抛错', () => {
    expect(extractWorkflowList(undefined)).toEqual([])
    expect(extractWorkflowList(null)).toEqual([])
    expect(extractWorkflowList({})).toEqual([])
    expect(extractWorkflowList('garbage')).toEqual([])
  })
})

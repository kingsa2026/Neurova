/**
 * collaboration startSession 载荷契约测试（根因修复防回归）
 *
 * 后端 CollaborationStart（collaboration_api.py）字段是 snake_case `template_id` +
 * `participants` + `context`，且无 camelCase alias、`extra='ignore'`。前端曾直接发
 * `{ templateId, name, description }` → 全部被后端当未知字段丢弃 → 模板/名称静默失效，
 * 会话恒为 "New Collaboration"。本测试锁定 api 边界把载荷映射为后端契约。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { startSession } from '@/api/modules/collaboration'

const mockPost = vi.mocked(api.post)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('collaboration startSession 载荷映射', () => {
  it('把 templateId 映射为 template_id、name/description 收进 context', async () => {
    await startSession({
      templateId: 'tpl-1',
      participants: ['agent-a', 'agent-b'],
      name: '我的协作',
      description: '说明文本',
    })

    expect(mockPost).toHaveBeenCalledWith('/collaboration/start', {
      template_id: 'tpl-1',
      participants: ['agent-a', 'agent-b'],
      context: { name: '我的协作', description: '说明文本' },
    })
  })

  it('不再向后端发送 camelCase templateId / 顶层 name/description', async () => {
    await startSession({ templateId: 't', participants: [], name: 'n', description: 'd' })

    const body = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(body).not.toHaveProperty('templateId')
    expect(body).not.toHaveProperty('name')
    expect(body).not.toHaveProperty('description')
  })
})

/**
 * S12 项目协作档案 API 契约测试
 *
 * getProjectCollaboration 挂既有 projects 域（GET /projects/{id}/collaboration，
 * 后端 projects_api.py），不新开端点域；本测试锁定 URL 形态与类型边界。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, message: 'success', data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { getProjectCollaboration } from '@/api/modules/collaboration'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getProjectCollaboration 契约', () => {
  it('GET /projects/{id}/collaboration（挂 projects 域，不新开端点域）', async () => {
    await getProjectCollaboration('project_abc123')
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/projects/project_abc123/collaboration')
  })

  it('返回信封的 data 即聚合档案（五类记录 + counts + summary）', async () => {
    const dossier = {
      project_id: 'project_abc123',
      generated_at: 1700000000,
      runs: [],
      events: [],
      candidates: [],
      approvals: [],
      room_messages: [],
      counts: { runs: 0, events: 0, candidates: 0, approvals: 0, room_messages: 0 },
      summary: null,
    }
    mockGet.mockResolvedValueOnce({ code: 0, message: 'success', data: dossier })
    const resp: any = await getProjectCollaboration('project_abc123')
    expect(resp.code).toBe(0)
    expect(resp.data).toEqual(dossier)
  })
})

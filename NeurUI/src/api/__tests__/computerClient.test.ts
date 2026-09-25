import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const del = vi.fn()

vi.mock('@/api', () => ({
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    delete: (...a: unknown[]) => del(...a),
  },
}))

import * as computerApi from '@/api/computer'

describe('computer 客户端走唯一 axios 实例', () => {
  beforeEach(() => {
    get.mockReset(); post.mockReset(); del.mockReset()
    get.mockResolvedValue([]); post.mockResolvedValue({}); del.mockResolvedValue(undefined)
  })

  it('listUserComputers 走共享实例且路径落在 /computers', async () => {
    await computerApi.listUserComputers()
    expect(get).toHaveBeenCalledWith('/computers')
  })

  it('getCloudComputer 走共享实例并带 company_id 查询', async () => {
    await computerApi.getCloudComputer('org-1')
    expect(get).toHaveBeenCalledWith('/computers/cloud', { params: { company_id: 'org-1' } })
  })

  it('createComputer 走共享实例（不再裸 post）', async () => {
    await computerApi.createComputer({ name: 'x' })
    expect(post).toHaveBeenCalledTimes(1)
    expect(String(post.mock.calls[0][0])).toBe('/computers')
  })

  it('deleteComputer 走共享实例', async () => {
    await computerApi.deleteComputer('cmp-1')
    expect(del).toHaveBeenCalledWith('/computers/cmp-1', { params: { hard: false } })
  })

  it('聚合导出 computerApi 暴露全部方法', () => {
    for (const name of [
      'listUserComputers', 'createComputer', 'getComputer', 'deleteComputer',
      'pairByOAComputer', 'revokeComputer', 'heartbeat', 'listAgentsOnComputer',
      'getCloudComputer', 'cleanupOfflineComputers',
    ]) {
      expect(typeof (computerApi.computerApi as Record<string, unknown>)[name]).toBe('function')
    }
  })
})

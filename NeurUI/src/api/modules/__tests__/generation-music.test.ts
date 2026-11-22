/**
 * 音乐生成 API 契约（M1/L5）：submitMusic 打 POST /generation/music、
 * getMusicTaskStatus 打 GET /generation/music/status/{task_id}，
 * 与既有 video 函数同形态（提交返回 task_id/status/protocol，轮询四态）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { apiPost, apiGet } = vi.hoisted(() => ({ apiPost: vi.fn(), apiGet: vi.fn() }))

vi.mock('@/api', () => ({
  default: { get: apiGet, post: apiPost, put: vi.fn(), delete: vi.fn() },
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { submitMusic, getMusicTaskStatus } from '../generation'

describe('generation music api（M1/L5 契约）', () => {
  beforeEach(() => {
    apiPost.mockReset()
    apiGet.mockReset()
  })

  it('submitMusic 打 POST /generation/music，载荷原样透传', async () => {
    apiPost.mockResolvedValue({ code: 0, data: { task_id: 't1', status: 'submitted', protocol: 'fal' } })
    const payload = { prompt: '轻快的钢琴曲', duration: 30 }
    const res: any = await submitMusic(payload)
    expect(apiPost).toHaveBeenCalledWith('/generation/music', payload)
    expect(res.data.task_id).toBe('t1')
    expect(res.data.status).toBe('submitted')
    expect(res.data.protocol).toBe('fal')
  })

  it('getMusicTaskStatus 打 GET /generation/music/status/{task_id}', async () => {
    apiGet.mockResolvedValue({
      code: 0,
      data: { task_id: 't1', status: 'succeeded', url: '/api/v1/generation/files/m1.mp3' },
    })
    const res: any = await getMusicTaskStatus('t1')
    expect(apiGet).toHaveBeenCalledWith('/generation/music/status/t1')
    expect(res.data.status).toBe('succeeded')
    expect(res.data.url).toBe('/api/v1/generation/files/m1.mp3')
  })
})

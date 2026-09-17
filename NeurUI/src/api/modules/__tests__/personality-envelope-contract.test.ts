import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: {} }),
  put: vi.fn().mockResolvedValue({ data: {} }),
  post: vi.fn().mockResolvedValue({ data: {} }),
}))

vi.mock('@/api', () => ({ default: apiMock }))

import * as growth from '../growth'

describe('personality envelope 契约（2026-09-16 个性档案空数据修复回归）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('BE envelope 响应下 getPersonality 的 res.data 即 profile（裸对象曾致 FE .data 恒 undefined）', async () => {
    // 修复前 BE 返回裸对象 {agent_id, traits, ...}（无 data 键）→ GrowthPage res.data 恒 undefined
    const beBody = {
      code: 0,
      message: 'success',
      data: { agent_id: 'a1', timestamp: 1, traits: { curiosity: 0.7 }, values: ['诚实'], communication_style: 'balanced', decision_style: 'analytical' },
    }
    apiMock.get.mockResolvedValueOnce(beBody)
    const res = await growth.getPersonality('a1')
    expect(apiMock.get).toHaveBeenCalledWith('/growth/personality', { params: { agent_id: 'a1' } })
    expect(res.data.traits).toEqual({ curiosity: 0.7 })
    expect(res.data.communication_style).toBe('balanced')
  })

  it('updatePersonality 返回 envelope.data 回读', async () => {
    const beBody = {
      code: 0,
      message: 'success',
      data: { agent_id: 'a2', traits: { openness: 0.8 }, values: [], communication_style: 'direct', decision_style: 'analytical' },
    }
    apiMock.put.mockResolvedValueOnce(beBody)
    const res = await growth.updatePersonality('a2', { traits: { openness: 0.8 } })
    expect(apiMock.put).toHaveBeenCalledWith(
      '/growth/personality',
      { traits: { openness: 0.8 } },
      { params: { agent_id: 'a2' } },
    )
    expect(res.data.traits).toEqual({ openness: 0.8 })
  })

  it('PersonalityProfile 契约字段与 BE 真实返回对齐（无幻影 style/tone）', async () => {
    const beBody = {
      code: 0,
      message: 'success',
      data: { agent_id: 'a1', timestamp: 1789000000, traits: {}, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    }
    apiMock.get.mockResolvedValueOnce(beBody)
    const res = await growth.getPersonality('a1')
    const p = res.data
    // 编译期字段：逐个访问验证接口形状（style/tone 已移除，不存在于类型）
    expect(p.agent_id).toBe('a1')
    expect(Array.isArray(p.values)).toBe(true)
    expect(typeof p.communication_style).toBe('string')
    expect(typeof p.decision_style).toBe('string')
  })
})

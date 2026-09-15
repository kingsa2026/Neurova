/**
 * growth API 模块契约测试（2026-09-15 反思/成长链路排查修复）
 *
 * 钉死三处前后端错位根因：
 * 1. agent_id 必须走 query——BE 端点用 Query 声明，body 传法被静默忽略
 *    （createQuestion/createReflection 曾恒落 default agent）
 * 2. answerQuestion 是 PUT + query(answer)，原 POST+body 恒 405
 * 3. getQuestions 参数是 limit/offset/answered（原 page/size 被 BE 忽略）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: {} }),
  post: vi.fn().mockResolvedValue({ data: {} }),
  put: vi.fn().mockResolvedValue({ data: {} }),
}))

vi.mock('@/api', () => ({ default: apiMock }))

import * as growth from '../growth'

describe('growth 模块 HTTP 契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.get.mockResolvedValue({ data: {} })
    apiMock.post.mockResolvedValue({ data: {} })
    apiMock.put.mockResolvedValue({ data: {} })
  })

  it('getCapabilities GET /growth/capabilities?agent_id=', async () => {
    await growth.getCapabilities('a1')
    expect(apiMock.get).toHaveBeenCalledWith('/growth/capabilities', { params: { agent_id: 'a1' } })
  })

  it('getQuestions 使用 limit/offset/answered 查询参并返回裸数组', async () => {
    await growth.getQuestions('a1', { limit: 50, offset: 10, answered: false })
    expect(apiMock.get).toHaveBeenCalledWith('/growth/questions', {
      params: { limit: 50, offset: 10, answered: false, agent_id: 'a1' },
    })
  })

  it('createQuestion 的 agent_id 走 query 而非 body', async () => {
    await growth.createQuestion('a1', '问题X')
    expect(apiMock.post).toHaveBeenCalledWith(
      '/growth/questions',
      { question: '问题X', question_type: 'curiosity' },
      { params: { agent_id: 'a1' } },
    )
  })

  it('answerQuestion 用 PUT + query(answer)', async () => {
    await growth.answerQuestion('a1', 'q1', '答案Y')
    expect(apiMock.put).toHaveBeenCalledWith(
      '/growth/questions/q1/answer',
      null,
      { params: { agent_id: 'a1', answer: '答案Y' } },
    )
  })

  it('createReflection 的 agent_id 走 query；type/insights/confidence 全量进 body（弹窗输入不丢弃）', async () => {
    await growth.createReflection('a1', '内容Z', 'insight', ['要点1', '要点2'], 0.8)
    expect(apiMock.post).toHaveBeenCalledWith(
      '/growth/reflection',
      { content: '内容Z', reflection_type: 'insight', insights: ['要点1', '要点2'], confidence: 0.8 },
      { params: { agent_id: 'a1' } },
    )
  })

  it('updatePersonality 的 agent_id 走 query 而非 body（BE 是 Query，body 传法被静默忽略→恒写 default agent）', async () => {
    await growth.updatePersonality('a2', { traits: { curiosity: 0.9 } })
    expect(apiMock.put).toHaveBeenCalledWith(
      '/growth/personality',
      { traits: { curiosity: 0.9 } },
      { params: { agent_id: 'a2' } },
    )
  })

  it('getReflections 归一 BE 裸数组条目（log_id/timestamp/reflection_type/confidence → id/created_at/category/quality）', async () => {
    apiMock.get.mockResolvedValueOnce([
      {
        log_id: 'L1', agent_id: 'a1', timestamp: 1789409845.3,
        reflection_type: 'performance', content: '正文', insights: ['洞察'], confidence: 0.8,
        related_memories: [], status: 'pending',
      },
    ])
    const list = await growth.getReflections('a1', { limit: 12, offset: 0 })
    expect(apiMock.get).toHaveBeenCalledWith('/growth/reflection', { params: { limit: 12, offset: 0, agent_id: 'a1' } })
    expect(list).toHaveLength(1)
    expect(list[0].id).toBe('L1')
    expect(list[0].category).toBe('performance')
    expect(list[0].quality).toBe(4)
    expect(list[0].created_at).toContain('2026')
  })

  it('getQuestions 直接返回 BE 裸数组（拦截器语义：Promise 值即 body）', async () => {
    apiMock.get.mockResolvedValueOnce([
      { id: 'q1', question_id: 'q1', agent_id: 'a1', question: '问题?', status: 'asked', answered: false, created_at: 1 },
    ])
    const list = await growth.getQuestions('a1', { limit: 50 })
    expect(list).toHaveLength(1)
    expect(list[0].status).toBe('asked')
  })
})

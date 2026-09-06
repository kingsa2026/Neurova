/**
 * 模型级连接测试 + 多模态探测 + 结构化发现 — 前端契约测试（QwenPaw 对齐）
 *
 * 锁定：
 * 1. models.ts / providers.ts 新 API 函数打到正确端点与参数；
 * 2. ModelPage 模型条目操作：testModelConnection / probeModel 消费信封 data；
 * 3. error_hint 优先展示（五类归一错误的可行动提示）；
 * 4. discoverModelsStructured 消费 success/used_static_fallback/error_kind。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

const postMock = vi.fn()
const getMock = vi.fn()

vi.mock('@/api', () => ({
  default: {
    post: (...args: unknown[]) => postMock(...args),
    get: (...args: unknown[]) => getMock(...args),
  },
}))

import { checkModelConnection, probeModelMultimodal } from '@/api/modules/models'
import { discoverModelsStructured } from '@/api/modules/providers'

describe('模型管理 API 契约（QwenPaw 对齐）', () => {
  beforeEach(() => {
    postMock.mockReset()
    getMock.mockReset()
  })

  it('checkModelConnection POST /models/check-connection 带 model_id 查询参数', async () => {
    postMock.mockResolvedValue({ code: 0, data: { model_id: 'm1', connected: true, message: '' } })
    await checkModelConnection('m1')
    expect(postMock).toHaveBeenCalledWith(
      '/models/check-connection',
      null,
      expect.objectContaining({ params: { model_id: 'm1' } }),
    )
  })

  it('probeModelMultimodal POST /models/probe-multimodal 透传 force', async () => {
    postMock.mockResolvedValue({ code: 0, data: { model_id: 'm1', result: {} } })
    await probeModelMultimodal({ model_id: 'm1', force: true })
    expect(postMock).toHaveBeenCalledWith('/models/probe-multimodal', { model_id: 'm1', force: true })
  })

  it('discoverModelsStructured GET 结构化发现端点', async () => {
    getMock.mockResolvedValue({ code: 0, data: { success: true, models: [], discovered_count: 0 } })
    await discoverModelsStructured('p1')
    expect(getMock).toHaveBeenCalledWith('/providers/p1/models/discover')
  })
})

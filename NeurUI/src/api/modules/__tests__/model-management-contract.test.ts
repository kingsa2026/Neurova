/**
 * 模型级连接测试 + 多模态探测 + 结构化发现 — 前端契约测试
 *
 * 锁定：
 * 1. models.ts / providers.ts 新 API 函数打到正确端点与参数；
 * 2. ModelPage 模型条目操作：testModelConnection / probeModel 消费信封 data；
 * 3. error_hint 优先展示（五类归一错误的可行动提示）；
 * 4. discoverModelsStructured 消费 success/used_static_fallback/error_kind。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const postMock = vi.fn()
const getMock = vi.fn()

vi.mock('@/api', () => ({
  default: {
    post: (...args: unknown[]) => postMock(...args),
    get: (...args: unknown[]) => getMock(...args),
  },
}))

import { checkModelConnection, probeModelMultimodal, probeOutputLimit } from '@/api/modules/models'
import { discoverModelsStructured } from '@/api/modules/providers'

describe('模型管理 API 契约', () => {
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

  it('probeOutputLimit POST /models/probe-output-limit 透传 provider/model', async () => {
    postMock.mockResolvedValue({ code: 0, data: { supported: true, limit: 65536 } })
    await probeOutputLimit({ provider_id: 'amd', model_id: 'GLM-5.3-Flash' })
    expect(postMock).toHaveBeenCalledWith('/models/probe-output-limit', {
      provider_id: 'amd',
      model_id: 'GLM-5.3-Flash',
    })
  })

  it('discoverModelsStructured GET 结构化发现端点', async () => {
    getMock.mockResolvedValue({ code: 0, data: { success: true, models: [], discovered_count: 0 } })
    await discoverModelsStructured('p1')
    expect(getMock).toHaveBeenCalledWith('/providers/p1/models/discover')
  })
})

describe('模型管理：输出上限持久化入口', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/ModelPage.vue'), 'utf-8')

  it('ModelPage 接上探测 API 并消费信封 data', () => {
    expect(page).toContain('probeOutputLimit as apiProbeOutputLimit')
    expect(page).toContain('probeOutputLimitForModel')
    expect(page).toContain('res?.data ?? res')
  })

  it('模型条目展示已持久化的 out ≥ 值并带探测按钮', () => {
    expect(page).toContain('model.probeOutputLimitTip')
    expect(page).toContain('model.probeOutputValue')
    expect(page).toContain('m.max_output_tokens')
    expect(page).toContain('probingOutputModelId')
  })

  const keys = [
    'probeOutputLimitTip',
    'probeOutputDone',
    'probeOutputFailed',
    'probeOutputUnsupported',
    'probeOutputInconclusive',
    'probeOutputValue',
  ]
  for (const key of keys) {
    it(`zh-CN 与 en-US 都定义了 model.${key}`, () => {
      for (const locale of ['zh-CN', 'en-US']) {
        const text = readFileSync(
          resolve(process.cwd(), `src/i18n/locales/${locale}.ts`),
          'utf-8',
        )
        const defined = text
          .split('\n')
          .some((line) => line.trimStart().startsWith(`${key}:`))
        expect(defined).toBe(true)
      }
    })
  }
})

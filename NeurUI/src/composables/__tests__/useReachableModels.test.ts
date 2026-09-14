import { describe, it, expect, vi, beforeEach } from 'vitest'

const listModelsMock = vi.fn()
vi.mock('@/api/modules/models', () => ({
  listModels: (...args: unknown[]) => listModelsMock(...args),
}))

import { buildModelOptions, useReachableModels } from '../useReachableModels'
import type { ModelItem } from '@/types/model'

const model = (over: Partial<ModelItem>): ModelItem =>
  ({
    id: 'm1',
    name: 'GPT-4',
    provider_id: 'openai',
    type: 'text',
    tags: [],
    enabled: true,
    capabilities: ['text'],
    is_active: false,
    ...over,
  }) as ModelItem

describe('buildModelOptions', () => {
  it('只保留 enabled 的模型', () => {
    const opts = buildModelOptions([model({ id: 'a' }), model({ id: 'b', enabled: false })])
    expect(opts.map((o) => o.value)).toEqual(['a'])
  })

  it('按 provider 过滤', () => {
    const opts = buildModelOptions(
      [model({ id: 'a', provider_id: 'openai' }), model({ id: 'b', provider_id: 'anthropic' })],
      'openai',
    )
    expect(opts.map((o) => o.value)).toEqual(['a'])
  })

  it('label 为「名称 (provider/模型ID)」便于区分同名模型', () => {
    const opts = buildModelOptions([model({ id: 'gpt-4', name: 'GPT-4', provider_id: 'openai' })])
    expect(opts[0].label).toBe('GPT-4 (openai/gpt-4)')
    expect(opts[0].provider_id).toBe('openai')
  })
})

  it('capability 过滤：生成类能力只出对应模型；非生成能力不过滤', () => {
    const ms = [
      model({ id: 'flux', capabilities: ['image_generation'] }),
      model({ id: 'seedance', capabilities: ['video_generation'] }),
      model({ id: 'chat', capabilities: ['text'] }),
      model({ id: 'naked' }), // 无 capabilities → 非生成过滤时保留
    ]
    expect(buildModelOptions(ms, undefined, 'image_generation').map(o => o.value)).toEqual(['flux'])
    expect(buildModelOptions(ms, undefined, 'video_generation').map(o => o.value)).toEqual(['seedance'])
    // text/vision 等不做能力过滤（chat 模型标记常缺，误伤教训）
    expect(buildModelOptions(ms, undefined, 'text').map(o => o.value)).toEqual(['flux', 'seedance', 'chat', 'naked'])
    expect(buildModelOptions(ms).map(o => o.value)).toEqual(['flux', 'seedance', 'chat', 'naked'])
  })

describe('useReachableModels', () => {
  beforeEach(() => {
    listModelsMock.mockReset()
  })

  it('load 拉取 /models 并兼容数组与 {models} 两种响应形状', async () => {
    listModelsMock.mockResolvedValueOnce({ data: { models: [model({ id: 'a' })] } })
    const { load, models } = useReachableModels()
    await load()
    expect(models.value.map((m) => m.id)).toEqual(['a'])

    listModelsMock.mockResolvedValueOnce({ data: [model({ id: 'b' })] })
    const inst2 = useReachableModels()
    await inst2.load()
    expect(inst2.models.value.map((m) => m.id)).toEqual(['b'])
  })

  it('load 失败时静默降级为空列表，不抛错', async () => {
    listModelsMock.mockRejectedValueOnce(new Error('network'))
    const { load, models } = useReachableModels()
    await expect(load()).resolves.toBeUndefined()
    expect(models.value).toEqual([])
  })

  it('selectModel 联动：选中模型自动回填其 provider', () => {
    const { selectedProviderId, selectModel } = useReachableModels()
    selectModel(model({ id: 'gpt-4', provider_id: 'openai' }))
    expect(selectedProviderId.value).toBe('openai')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import {
  filterProviderModels,
  getProviderSeries,
  mergeDiscoveredModels,
} from '@/api/modules/providers'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('provider filter/merge API', () => {
  it('filterProviderModels posts filter body to /providers/{id}/models/filter', async () => {
    await filterProviderModels('openrouter', {
      providers: ['openai'],
      input_modalities: ['image'],
      is_free: true,
    })
    expect(mockPost).toHaveBeenCalledWith(
      '/providers/openrouter/models/filter',
      { providers: ['openai'], input_modalities: ['image'], is_free: true },
    )
  })

  it('filterProviderModels sends empty body by default (include missing)', async () => {
    await filterProviderModels('openrouter')
    expect(mockPost).toHaveBeenCalledWith(
      '/providers/openrouter/models/filter',
      {},
    )
    // 避免遗漏可选键:显式传 undefined 应被保留而非缺失
    await filterProviderModels('openrouter', { max_prompt_price: 0 })
    expect(mockPost).toHaveBeenLastCalledWith(
      '/providers/openrouter/models/filter',
      { max_prompt_price: 0 },
    )
  })

  it('getProviderSeries calls GET /providers/{id}/models/series', async () => {
    await getProviderSeries('openrouter')
    expect(mockGet).toHaveBeenCalledWith('/providers/openrouter/models/series')
  })

  it('mergeDiscoveredModels posts model ids to merge endpoint', async () => {
    await mergeDiscoveredModels('openrouter', ['openai/gpt-4o'])
    expect(mockPost).toHaveBeenCalledWith(
      '/providers/openrouter/models/discover/merge',
      { model_ids: ['openai/gpt-4o'] },
    )
  })

  it('mergeDiscoveredModels with null merges all candidates', async () => {
    await mergeDiscoveredModels('openrouter', null)
    expect(mockPost).toHaveBeenCalledWith(
      '/providers/openrouter/models/discover/merge',
      { model_ids: null },
    )
  })
})

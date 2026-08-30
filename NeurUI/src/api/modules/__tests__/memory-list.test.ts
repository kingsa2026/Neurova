import { describe, it, expect, vi } from 'vitest'

// memory 模块顶层依赖 @/api，统一 mock（与 api-modules.test.ts 同款）
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import { extractMemoryList } from '@/api/modules/memory'

const m = { id: 'm1', content: 'hi' }

describe('extractMemoryList', () => {
  it('解析后端 {count, memories} 信封（recall/get_hot/get_crystallized 的实际形态）', () => {
    expect(extractMemoryList({ count: 1, memories: [m] })).toEqual({ items: [m], total: 1 })
  })

  it('兼容 {items, total} 分页信封', () => {
    expect(extractMemoryList({ items: [m], total: 5 })).toEqual({ items: [m], total: 5 })
  })

  it('兼容数组形态', () => {
    expect(extractMemoryList([m])).toEqual({ items: [m], total: 1 })
  })

  it('count 缺失时 total 回退为列表长度', () => {
    expect(extractMemoryList({ memories: [m, m] })).toEqual({ items: [m, m], total: 2 })
  })

  it('空/非法输入返回空列表', () => {
    expect(extractMemoryList(undefined)).toEqual({ items: [], total: 0 })
    expect(extractMemoryList(null)).toEqual({ items: [], total: 0 })
    expect(extractMemoryList({})).toEqual({ items: [], total: 0 })
    expect(extractMemoryList('bad')).toEqual({ items: [], total: 0 })
  })
})

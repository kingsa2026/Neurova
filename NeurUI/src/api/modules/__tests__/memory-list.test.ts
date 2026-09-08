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

import { extractMemoryList, MEMORY_TYPE_BY_TAB } from '@/api/modules/memory'

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

describe('MEMORY_TYPE_BY_TAB（页签 → memory_type 契约）', () => {
  it('工作记忆页签（short_term）→ working', () => {
    expect(MEMORY_TYPE_BY_TAB.short_term).toBe('working')
  })

  it('长期记忆页签（long_term）→ 排除 working 的五类逗号多值', () => {
    const mt = MEMORY_TYPE_BY_TAB.long_term
    expect(mt).toBeTruthy()
    const parts = String(mt).split(',')
    expect(parts).toContain('semantic')
    expect(parts).toContain('episodic')
    expect(parts).not.toContain('working')
  })

  it('情景/语义页签 → 同名 memory_type', () => {
    expect(MEMORY_TYPE_BY_TAB.episodic).toBe('episodic')
    expect(MEMORY_TYPE_BY_TAB.semantic).toBe('semantic')
  })

  it('全部/热点/结晶页签不映射（全量或专用端点）', () => {
    expect(MEMORY_TYPE_BY_TAB.all).toBeUndefined()
    expect(MEMORY_TYPE_BY_TAB.hot).toBeUndefined()
    expect(MEMORY_TYPE_BY_TAB.crystallized).toBeUndefined()
  })
})

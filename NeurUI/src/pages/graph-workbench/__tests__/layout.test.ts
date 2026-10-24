// -*- coding: utf-8 -*-
// 2D 布局纯函数判据：确定性、类型分列、无同位重叠。
import { describe, expect, it } from 'vitest'

import { layeredLayout } from '@/pages/graph-workbench/layout'

const NODES = [
  { id: 'a', label: 'A', type: 'concept' },
  { id: 'b', label: 'B', type: 'relation' },
  { id: 'c', label: 'C', type: 'concept' },
  { id: 'd', label: 'D', type: '' }, // 无类型节点进 other 桶，不丢
]

describe('layeredLayout（工作台 2D 确定性布局）', () => {
  it('同类型节点同列且纵向分布', () => {
    const pos = layeredLayout(NODES)
    const a = pos.get('a')!
    const c = pos.get('c')!
    expect(a.x).toBe(c.x)
    expect(c.y).toBeGreaterThan(a.y)
  })

  it('不同类型节点分列', () => {
    const pos = layeredLayout(NODES)
    expect(pos.get('a')!.x).not.toBe(pos.get('b')!.x)
  })

  it('任何两节点不重叠', () => {
    const pos = layeredLayout(NODES)
    const seen = new Set(Array.from(pos.values()).map((p) => `${p.x},${p.y}`))
    expect(seen.size).toBe(NODES.length)
  })

  it('确定性：同一份输入两次布局逐点相等', () => {
    expect([...layeredLayout(NODES)]).toEqual([...layeredLayout([...NODES])])
  })

  it('空图安全', () => {
    expect(layeredLayout([]).size).toBe(0)
  })
})

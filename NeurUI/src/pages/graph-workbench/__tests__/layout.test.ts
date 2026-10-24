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

  it('同类型超过每列上限自动折子列', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      id: `n${i}`, label: `N${i}`, type: 'concept',
    }))
    const pos = layeredLayout(many)
    // 前 8 个在第 0 列，第 9 个折到第 1 子列、行位回到 0
    expect(pos.get('n7')!.x).toBe(0)
    expect(pos.get('n8')!.x).toBe(240)
    expect(pos.get('n8')!.y).toBe(0)
    // 折行后仍然无重叠
    const seen = new Set(Array.from(pos.values()).map((p) => `${p.x},${p.y}`))
    expect(seen.size).toBe(9)
  })

  it('折行占用的列不与后续类型重叠', () => {
    const nodes = [
      ...Array.from({ length: 9 }, (_, i) => ({
        id: `c${i}`, label: `C${i}`, type: 'concept',
      })),
      { id: 'r0', label: 'R', type: 'relation' },
    ]
    const pos = layeredLayout(nodes)
    // concept 占 0/1 两列，relation 落在第 2 列
    expect(pos.get('r0')!.x).toBe(480)
  })
})

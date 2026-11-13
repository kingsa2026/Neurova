// -*- coding: utf-8 -*-
// 力导向布局判据（用户四点诉求的可测形态）：
//  1. 全节点有位；2. 无重叠（成对屏幕距离 ≥ 碰撞直径）；
//  3. 连通边长有界（线短而匀，不出现横穿全图的超长关系线）；
//  4. 聚焦根近原点（选中节点居中语义）；5. 包围盒有界；6. 确定性。
import { describe, expect, it } from 'vitest'

import { forceLayoutFull, LAYOUT_COLLIDE_DIAMETER } from '@/pages/graph-workbench/forceLayout'

/** forceLayout 包装已随死码退役批删除（P3-1）：断言改走 forceLayoutFull().positions */
function forceLayout(
  nodes: Array<{ id: string; label: string; type: string }>,
  edges: Array<{ source: string; target: string }>,
  rootId?: string,
) {
  return forceLayoutFull(nodes, edges, rootId).positions
}

const STAR = {
  nodes: [
    { id: 'h', label: 'hub', type: 'concept' },
    { id: 'a', label: 'A', type: 'concept' },
    { id: 'b', label: 'B', type: 'concept' },
    { id: 'c', label: 'C', type: 'concept' },
    { id: 'a1', label: 'A1', type: 'concept' },
    { id: 'a2', label: 'A2', type: 'concept' },
    { id: 'b1', label: 'B1', type: 'concept' },
  ],
  edges: [
    { source: 'h', target: 'a' }, { source: 'h', target: 'b' },
    { source: 'h', target: 'c' }, { source: 'a', target: 'a1' },
    { source: 'a', target: 'a2' }, { source: 'b', target: 'b1' },
  ],
}

describe('forceLayout（工作台 2D 力导向布局）', () => {
  it('全节点有位', () => {
    const pos = forceLayout(STAR.nodes, STAR.edges, 'h')
    expect(pos.size).toBe(STAR.nodes.length)
    for (const n of STAR.nodes) expect(pos.get(n.id)).toBeDefined()
  })

  it('无重叠：任意两节点屏幕距离不小于碰撞直径', () => {
    const pos = forceLayout(STAR.nodes, STAR.edges, 'h')
    const pts = [...pos.values()]
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)
        expect(d, `节点对 ${i}/${j} 距离 ${d.toFixed(1)} < 碰撞直径`).toBeGreaterThanOrEqual(
          LAYOUT_COLLIDE_DIAMETER - 0.5,
        )
      }
    }
  })

  it('密集星形（1 枢纽 + 16 叶）互不重叠', () => {
    const nodes = [
      { id: 'h', label: 'hub', type: 't' },
      ...Array.from({ length: 16 }, (_, i) => ({ id: `c${i}`, label: `C${i}`, type: 't' })),
    ]
    const edges = Array.from({ length: 16 }, (_, i) => ({ source: 'h', target: `c${i}` }))
    const pos = forceLayout(nodes, edges, 'h')
    const pts = [...pos.values()]
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        expect(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)).toBeGreaterThanOrEqual(
          LAYOUT_COLLIDE_DIAMETER - 0.5,
        )
      }
    }
  })

  it('连通边长有界：关系线不出现横穿全图的超长边', () => {
    const pos = forceLayout(STAR.nodes, STAR.edges, 'h')
    for (const e of STAR.edges) {
      const a = pos.get(e.source)!
      const b = pos.get(e.target)!
      const d = Math.hypot(a.x - b.x, a.y - b.y)
      expect(d, `边 ${e.source}->${e.target} 长度 ${d.toFixed(0)} 超界`).toBeLessThanOrEqual(400)
    }
  })

  it('聚焦根近原点（选中节点居中语义）', () => {
    const pos = forceLayout(STAR.nodes, STAR.edges, 'a1')
    const root = pos.get('a1')!
    expect(Math.hypot(root.x, root.y)).toBeLessThan(40)
  })

  it('多分量与孤立点包围盒有界', () => {
    const nodes = [
      { id: 'h', label: 'hub', type: 't' },
      { id: 'a', label: 'A', type: 't' },
      ...Array.from({ length: 60 }, (_, i) => ({ id: `iso${i}`, label: `I${i}`, type: 't' })),
    ]
    const edges = [{ source: 'h', target: 'a' }]
    const pos = forceLayout(nodes, edges, 'h')
    for (const p of pos.values()) {
      expect(Math.abs(p.x)).toBeLessThan(3000)
      expect(Math.abs(p.y)).toBeLessThan(3000)
    }
  })

  it('确定性：同一份输入两次布局逐点相等', () => {
    const a = forceLayout([...STAR.nodes], STAR.edges.map((e) => ({ ...e })), 'h')
    const b = forceLayout([...STAR.nodes], STAR.edges.map((e) => ({ ...e })), 'h')
    expect([...a]).toEqual([...b])
  })
})

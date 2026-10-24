// -*- coding: utf-8 -*-
// 放射布局判据：树边（父→子径向线段）零交叉、全节点有位、无同位、确定性。
import { describe, expect, it } from 'vitest'

import { radialLayout, DEFAULT_TOTAL_RADIUS } from '@/pages/graph-workbench/radial'

interface Seg { x1: number; y1: number; x2: number; y2: number }

/** 严格线段相交（共享端点/共线不算）——标准方向函数四象限判定。 */
function segCross(a: Seg, b: Seg): boolean {
  const orient = (ax: number, ay: number, bx: number, by: number, cx: number, cy: number) =>
    (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  const d1 = orient(b.x1, b.y1, b.x2, b.y2, a.x1, a.y1)
  const d2 = orient(b.x1, b.y1, b.x2, b.y2, a.x2, a.y2)
  const d3 = orient(a.x1, a.y1, a.x2, a.y2, b.x1, b.y1)
  const d4 = orient(a.x1, a.y1, a.x2, a.y2, b.x2, b.y2)
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0))
}

interface NamedSeg extends Seg { p: string; c: string }

function treeSegments(
  pos: Map<string, { x: number; y: number }>,
  treeEdges: Array<[string, string]>,
): NamedSeg[] {
  return treeEdges.map(([p, c]) => ({
    p, c,
    x1: pos.get(p)!.x, y1: pos.get(p)!.y,
    x2: pos.get(c)!.x, y2: pos.get(c)!.y,
  }))
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
// BFS 树边（无环图即全部边）。
const STAR_TREE: Array<[string, string]> = [
  ['h', 'a'], ['h', 'b'], ['h', 'c'],
  ['a', 'a1'], ['a', 'a2'], ['b', 'b1'],
]

describe('radialLayout（工作台 2D 放射布局）', () => {
  it('树边零交叉（布局的核心承诺）', () => {
    const pos = radialLayout(STAR.nodes, STAR.edges, 'h')
    const segs = treeSegments(pos, STAR_TREE)
    for (let i = 0; i < segs.length; i++) {
      for (let j = i + 1; j < segs.length; j++) {
        // 共享端点的两条边是连续折线，四符号判定必误报——几何上不叫交叉。
        const shared = segs[i].p === segs[j].p || segs[i].p === segs[j].c
          || segs[i].c === segs[j].p || segs[i].c === segs[j].c
        if (shared) continue
        expect(segCross(segs[i], segs[j]),
          `树边 ${segs[i].p}->${segs[i].c} 与 ${segs[j].p}->${segs[j].c} 交叉`).toBe(false)
      }
    }
  })

  it('根在圆心，半径按层深比例归一到总半径', () => {
    const pos = radialLayout(STAR.nodes, STAR.edges, 'h')
    const h = pos.get('h')!
    expect(Math.hypot(h.x, h.y)).toBeLessThan(1e-9)
    // 星形最大深度 2：一层半径 = 总半径/2，二层 = 总半径（角度不同半径确定）。
    expect(Math.hypot(pos.get('a')!.x, pos.get('a')!.y)).toBeCloseTo(DEFAULT_TOTAL_RADIUS / 2, 6)
    expect(Math.hypot(pos.get('a1')!.x, pos.get('a1')!.y)).toBeCloseTo(DEFAULT_TOTAL_RADIUS, 6)
  })

  it('全节点有位且无同位重叠', () => {
    const pos = radialLayout(STAR.nodes, STAR.edges, 'h')
    expect(pos.size).toBe(STAR.nodes.length)
    const seen = new Set(Array.from(pos.values()).map((p) => `${p.x},${p.y}`))
    expect(seen.size).toBe(STAR.nodes.length)
  })

  it('环边不炸：三角形图仍全节点有位', () => {
    const nodes = [
      { id: 'x', label: 'X', type: 't' },
      { id: 'y', label: 'Y', type: 't' },
      { id: 'z', label: 'Z', type: 't' },
    ]
    const edges = [
      { source: 'x', target: 'y' }, { source: 'y', target: 'z' },
      { source: 'z', target: 'x' },
    ]
    const pos = radialLayout(nodes, edges, 'x')
    expect(pos.size).toBe(3)
    expect(pos.get('x')).toBeDefined()
  })

  it('两个连通分量都有位置且不叠圆心', () => {
    const nodes = [
      { id: 'h', label: 'hub', type: 't' },
      { id: 'a', label: 'A', type: 't' },
      { id: 'u', label: 'U', type: 't' },
      { id: 'v', label: 'V', type: 't' },
    ]
    const edges = [
      { source: 'h', target: 'a' }, { source: 'u', target: 'v' },
    ]
    const pos = radialLayout(nodes, edges, 'h')
    expect(pos.size).toBe(4)
    // 第二分量的根半径已错开，不与主分量根同点。
    const h = pos.get('h')!, u = pos.get('u')!
    expect(Math.hypot(u.x - h.x, u.y - h.y)).toBeGreaterThan(1)
  })

  it('多分量包围盒有界（分量根半径封顶回归判据）', () => {
    // 1 个主分量 + 60 个孤立分量：根半径曾随序号线性爆涨到 38710px。
    const nodes = [
      { id: 'h', label: 'hub', type: 't' },
      { id: 'a', label: 'A', type: 't' },
      ...Array.from({ length: 60 }, (_, i) => ({ id: `iso${i}`, label: `I${i}`, type: 't' })),
    ]
    const edges = [{ source: 'h', target: 'a' }]
    const pos = radialLayout(nodes, edges, 'h')
    for (const p of pos.values()) {
      expect(Math.abs(p.x)).toBeLessThan(DEFAULT_TOTAL_RADIUS * 3)
      expect(Math.abs(p.y)).toBeLessThan(DEFAULT_TOTAL_RADIUS * 3)
    }
  })

  it('密集层不重叠：同层相邻节点屏幕距离不小于最小弧长', () => {
    // 12 个孩子挤一层：容量半径必须把圆周撑到弧长 ≥ MIN_ARC。
    const nodes = [
      { id: 'h', label: 'hub', type: 't' },
      ...Array.from({ length: 12 }, (_, i) => ({
        id: `c${i}`, label: `C${i}`, type: 't',
      })),
    ]
    const edges = Array.from({ length: 12 }, (_, i) => ({
      source: 'h', target: `c${i}`,
    }))
    const pos = radialLayout(nodes, edges, 'h')
    const ring = Array.from({ length: 12 }, (_, i) => pos.get(`c${i}`)!)
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i]
      const b = ring[(i + 1) % ring.length]
      expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(100)
    }
  })

  it('确定性：同一份输入两次布局逐点相等', () => {
    expect([...radialLayout(STAR.nodes, STAR.edges, 'h')])
      .toEqual([...radialLayout([...STAR.nodes], STAR.edges.map((e) => ({ ...e })), 'h')])
  })

  it('选中节点作为根（聚焦语义：点击后以其为圆心）', () => {
    const pos = radialLayout(STAR.nodes, STAR.edges, 'a1')
    expect(Math.hypot(pos.get('a1')!.x, pos.get('a1')!.y)).toBeLessThan(1e-9)
  })
})

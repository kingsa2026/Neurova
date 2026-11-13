// C3 性能预算门行为断言（specs/2026-11-12 §18）：
// 超预算降级（不卡主线程）＋未超预算正常模拟＋确定性不破。
import { describe, expect, it } from 'vitest'
import {
  forceLayoutFull,
  LAYOUT_NODE_BUDGET,
  LAYOUT_COLLIDE_DIAMETER,
  type LayoutNode,
  type LayoutEdge,
} from '../forceLayout'

function makeNodes(count: number): LayoutNode[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `n${i}`,
    label: `Node ${i}`,
    type: 'test',
  }))
}

function makeEdges(count: number, nodeCount: number): LayoutEdge[] {
  return Array.from({ length: count }, (_, i) => ({
    source: `n${i % nodeCount}`,
    target: `n${(i + 1) % nodeCount}`,
  }))
}

describe('forceLayout performance budget', () => {
  it('under budget: full simulation', () => {
    const nodes = makeNodes(10)
    const edges = makeEdges(10, 10)
    const result = forceLayoutFull(nodes, edges)
    expect(result.simulated).toBe(true)
    expect(result.positions.size).toBe(10)
    expect(result.nodeCount).toBe(10)
  })

  it('over budget: grid fallback (no tick simulation)', () => {
    const count = LAYOUT_NODE_BUDGET + 10
    const nodes = makeNodes(count)
    const result = forceLayoutFull(nodes, [])
    expect(result.simulated).toBe(false)
    expect(result.positions.size).toBe(count)
    // 网格撒点：坐标确定性
    expect(result.positions.get('n0')).toEqual({ x: 0, y: 0 })
  })

  it('budget constant is honest', () => {
    expect(LAYOUT_NODE_BUDGET).toBeGreaterThan(0)
    expect(LAYOUT_NODE_BUDGET).toBeLessThanOrEqual(1000)
  })

  it('deterministic: same input same output', () => {
    const nodes = makeNodes(20)
    const edges = makeEdges(30, 20)
    const r1 = forceLayoutFull(nodes, edges)
    const r2 = forceLayoutFull(nodes, edges)
    expect(r1.simulated).toBe(r2.simulated)
    for (const [id, pos] of r1.positions) {
      expect(r2.positions.get(id)).toEqual(pos)
    }
  })
})

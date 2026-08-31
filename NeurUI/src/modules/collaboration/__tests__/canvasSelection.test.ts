/**
 * canvasSelection 纯函数测试 — TDD 红灯先行（遗留 F：框选多选）。
 *
 * - normalizeRect(start, cur)：负向拖拽归一化为 {x,y,w,h}
 * - nodesInRect(nodes, rect, nodeSize)：矩形相交命中（默认节点估算 140×140，
 *   与 fitView 的估算一致）
 */
import { describe, expect, it } from 'vitest'
import { normalizeRect, nodesInRect } from '../canvasSelection'

const node = (id: string, x: number, y: number) => ({
  id,
  label: id,
  type: 'builtin:llm',
  icon: '🤖',
  position: { x, y },
  inputs: [],
  outputs: [],
  config: {},
})

describe('normalizeRect', () => {
  it('正向拖拽原样', () => {
    expect(normalizeRect(10, 20, 110, 120)).toEqual({ x: 10, y: 20, w: 100, h: 100 })
  })
  it('负向拖拽归一化', () => {
    expect(normalizeRect(110, 120, 10, 20)).toEqual({ x: 10, y: 20, w: 100, h: 100 })
  })
  it('零尺寸', () => {
    expect(normalizeRect(5, 5, 5, 5)).toEqual({ x: 5, y: 5, w: 0, h: 0 })
  })
})

describe('nodesInRect', () => {
  const nodes = [node('a', 0, 0), node('b', 200, 200), node('c', 1000, 1000)]

  it('框住 a（0,0 起 140×140 估算相交）', () => {
    const rect = normalizeRect(-10, -10, 50, 50)
    expect(nodesInRect(nodes, rect)).toEqual(['a'])
  })

  it('框住 a+b（大框）', () => {
    const rect = normalizeRect(-10, -10, 500, 500)
    expect(nodesInRect(nodes, rect).sort()).toEqual(['a', 'b'])
  })

  it('小框与节点部分相交即命中', () => {
    // rect 只盖住 b 的左上角一点（起点 195,195 → 终点 215,215）
    const rect = normalizeRect(195, 195, 215, 215)
    expect(nodesInRect(nodes, rect)).toEqual(['b'])
  })

  it('远处节点不命中', () => {
    const rect = normalizeRect(-10, -10, 100, 100)
    expect(nodesInRect(nodes, rect)).not.toContain('c')
  })

  it('自定义节点尺寸生效', () => {
    const rect = normalizeRect(80, 80, 10, 10)
    // 默认 140 尺寸：a 覆盖 (0,0)-(140,140) → 命中；若尺寸 0 则不命中
    expect(nodesInRect(nodes, rect)).toEqual(['a'])
    expect(nodesInRect(nodes, rect, { w: 0, h: 0 })).toEqual([])
  })
})

/**
 * canvasPan — 无限画布视口平移纯函数（空格+左键拖拽）+ 节点落点坐标。
 *
 * 修复根因（画布左上方无法拖放，存在硬边界）：
 *   原 addNodeAt / startDrag 用 Math.max(0, …) 把节点坐标钳制到 ≥ 0——
 *   画布平移后（panX > 0），屏幕左上区域对应的画布坐标可 < 0，
 *   节点落点被硬拽回原点，(0,0) 成了不可逾越的边界，"无线画布"名不副实。
 *   后端契约与 canvasClipboard 粘贴均无此限制（粘贴支持负坐标），
 *   修法为移除钳制、落点中心对齐（60/20 偏移保持原视觉）。
 *
 * 契约：
 *   1. dropNodePosition：落点允许负值（无限画布无原点边界）；
 *   2. panByDrag：空格+拖拽平移按屏幕像素 1:1 累加（与滚轮平移一致，不随 zoom 缩放）；
 *   3. shouldPanOnSpace：激活判定 = 空格按下 + 左键 + 事件命中画布容器；
 *      未按空格时画布行为（节点拖拽/框选/连线）不受任何影响。
 */
import { describe, expect, it } from 'vitest'
import {
  DROP_NODE_OFFSET,
  dropNodePosition,
  panByDrag,
  shouldPanOnSpace,
} from '../canvasPan'

describe('panByDrag', () => {
  it('新 pan = 起点 pan + 屏幕像素位移（1:1）', () => {
    expect(
      panByDrag({ panX: 100, panY: 200 }, { x: 10, y: 20 }, { x: 35, y: 5 }),
    ).toEqual({ panX: 125, panY: 185 })
  })

  it('负向位移（向左上拖）同样按增量累加', () => {
    expect(
      panByDrag({ panX: 0, panY: 0 }, { x: 50, y: 50 }, { x: -50, y: -20 }),
    ).toEqual({ panX: -100, panY: -70 })
  })

  it('零位移保持起点 pan', () => {
    expect(
      panByDrag({ panX: -300, panY: 12 }, { x: 20, y: 20 }, { x: 20, y: 20 }),
    ).toEqual({ panX: -300, panY: 12 })
  })
})

describe('dropNodePosition', () => {
  it('默认将节点中心对齐落点（左上角 = 指针 - 节点中心偏移）', () => {
    expect(DROP_NODE_OFFSET).toEqual({ x: 60, y: 20 })
    expect(dropNodePosition(200, 120)).toEqual({ x: 140, y: 100 })
  })

  it('指针位于平移后视口左上（画布坐标 < 0）时返回负值，不钳制——修复边界 bug', () => {
    const p = dropNodePosition(-80, -40)
    expect(p.x).toBeLessThan(0)
    expect(p.y).toBeLessThan(0)
  })

  it('支持自定义偏移', () => {
    expect(dropNodePosition(100, 100, { x: 10, y: 10 })).toEqual({ x: 90, y: 90 })
  })
})

describe('shouldPanOnSpace', () => {
  it('空格 + 左键 + 画布内 → 激活', () => {
    expect(shouldPanOnSpace(true, 0, true)).toBe(true)
  })

  it('未按空格 → 不激活（节点拖拽/框选照旧）', () => {
    expect(shouldPanOnSpace(false, 0, true)).toBe(false)
  })

  it('非左键（右键/中键）→ 不激活', () => {
    expect(shouldPanOnSpace(true, 2, true)).toBe(false)
    expect(shouldPanOnSpace(true, 1, true)).toBe(false)
  })

  it('事件命中画布外（面板/属性区）→ 不激活', () => {
    expect(shouldPanOnSpace(true, 0, false)).toBe(false)
  })
})

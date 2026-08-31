/**
 * canvasMinimap 纯函数测试 — TDD 红灯先行（遗留 F：小地图）。
 *
 * - computeMinimapLayout(nodes, viewport, containerSize, miniSize)：
 *   节点包围盒 → 缩放系数/居中偏移/节点 mini 矩形 + 视口矩形 + 内容原点
 * - miniClickToPan(click, layout, containerSize)：mini 点击 → 新 panX/panY
 *   （点击点对应的画布坐标居中到视口）
 */
import { describe, expect, it } from 'vitest'
import { computeMinimapLayout, miniClickToPan } from '../canvasMinimap'

const nodes = [
  { id: 'a', position: { x: 0, y: 0 } },
  { id: 'b', position: { x: 700, y: 400 } },
]

const viewport = { zoom: 1, panX: 0, panY: 0 }
const container = { w: 1200, h: 800 }
const mini = { w: 180, h: 120 }

describe('computeMinimapLayout', () => {
  it('包围盒与缩放：留边距后 fit 到 mini', () => {
    const layout = computeMinimapLayout(nodes, viewport, container, mini)
    expect(layout.scale).toBeGreaterThan(0)
    expect(layout.scale).toBeLessThanOrEqual(1)
    for (const m of layout.nodeRects) {
      expect(m.x).toBeGreaterThanOrEqual(layout.offsetX - 1)
      expect(m.y).toBeGreaterThanOrEqual(layout.offsetY - 1)
      expect(m.x + m.w).toBeLessThanOrEqual(mini.w + 1)
      expect(m.y + m.h).toBeLessThanOrEqual(mini.h + 1)
    }
    // 内容原点 = bbox 左上（画布坐标）
    expect(layout.contentOrigin).toEqual({ x: 0, y: 0 })
  })

  it('视口矩形按 zoom/pan 换算', () => {
    const layout = computeMinimapLayout(
      nodes, { zoom: 2, panX: -100, panY: -50 }, container, mini,
    )
    expect(layout.viewportRect.w).toBeCloseTo((container.w / 2) * layout.scale, 5)
    expect(layout.viewportRect.h).toBeCloseTo((container.h / 2) * layout.scale, 5)
  })

  it('空节点不崩溃且 scale 为默认', () => {
    const layout = computeMinimapLayout([], viewport, container, mini)
    expect(layout.nodeRects).toEqual([])
    expect(layout.scale).toBeGreaterThan(0)
  })
})

describe('miniClickToPan', () => {
  it('点击 mini 中心 → 内容中心画布坐标居中', () => {
    const layout = computeMinimapLayout(nodes, viewport, container, mini)
    const pan = miniClickToPan({ x: mini.w / 2, y: mini.h / 2 }, layout, container)
    // 新视口中心（画布坐标）= mini 中心对应的画布点
    const contentCx = (mini.w / 2 - layout.offsetX) / layout.scale + layout.contentOrigin.x
    const contentCy = (mini.h / 2 - layout.offsetY) / layout.scale + layout.contentOrigin.y
    expect(container.w / 2 - pan.panX).toBeCloseTo(contentCx, 3)
    expect(container.h / 2 - pan.panY).toBeCloseTo(contentCy, 3)
  })
})

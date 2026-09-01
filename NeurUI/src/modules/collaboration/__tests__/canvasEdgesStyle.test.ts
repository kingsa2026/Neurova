/**
 * 画布连线层 CSS 契约测试 — 防回归（节点拖出首屏后连线截断事故）。
 *
 * 根因：<svg class="canvas-edges"> 是 100%×100%（= 画布容器 1200×800），
 * SVG 默认 overflow:hidden——而边端点是画布坐标（可到数千 px），
 * 超出 SVG 自身坐标空间的线段被裁剪 → 节点拖出后连线在屏边界截断。
 * 修复：.canvas-edges 必须 overflow: visible。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const vueSrc = readFileSync(
  resolve(process.cwd(), 'src/modules/collaboration/CanvasDesignerPage.vue'),
  'utf-8',
)

describe('canvas-edges overflow contract', () => {
  it('.canvas-edges 规则必须声明 overflow: visible', () => {
    const blockMatch = vueSrc.match(/\.canvas-edges\s*\{[^}]*\}/)
    expect(blockMatch, '未找到 .canvas-edges 样式块').not.toBeNull()
    expect(blockMatch![0]).toContain('overflow: visible')
  })

  it('连线层保持 pointer-events: none（不挡节点交互）', () => {
    const block = vueSrc.match(/\.canvas-edges\s*\{[^}]*\}/)![0]
    expect(block).toContain('pointer-events: none')
  })

  it('方向箭头：defs 存在两个 marker 且边线引用 arrow（选中态换色）', () => {
    expect(vueSrc).toContain('<marker')
    expect(vueSrc).toContain('id="edge-arrow"')
    expect(vueSrc).toContain('id="edge-arrow-selected"')
    expect(vueSrc).toContain('orient="auto"')
    expect(vueSrc).toMatch(/marker-end: url\(#edge-arrow\)/)
    expect(vueSrc).toMatch(/marker-end: url\(#edge-arrow-selected\)/)
  })

  it('端口连接点扩大：10px 可视 + 伪元素命中热区', () => {
    const dotBlock = vueSrc.match(/\.port-dot \{[^}]*\}/)![0]
    expect(dotBlock).toContain('width: 10px')
    expect(dotBlock).toContain('height: 10px')
    expect(vueSrc).toMatch(/\.port-dot::before[^{]*\{[^}]*inset: -3px[^}]*\}/)
  })
})

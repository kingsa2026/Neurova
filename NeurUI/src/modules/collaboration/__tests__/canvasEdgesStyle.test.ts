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

// 行尾归一后再做文本比对：本仓在 Windows 上以 CRLF 检出（git 的 core.autocrlf），
// 而下面那枚锚点写的是 `'</div>\n\n        <!-- 缩放控制栏'`——LF 字面量在 CRLF 的
// 工作树里永远 indexOf 不到，于是这一格在 Linux 绿、在 Windows 恒红，红的却不是
// 画布结构（判据绑了机器形态，与台账 §6-96 那条同一族，只是这里绑的是行尾）。
// 该格要守的是"悬浮层在 transform 容器之外"这一**次序**，与行尾字节无关。
const vueSrc = readFileSync(
  resolve(process.cwd(), 'src/modules/collaboration/CanvasDesignerPage.vue'),
  'utf-8',
).replace(/\r\n/g, '\n')

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

  it('悬浮层（提示行/缩放栏/小地图）位于 transform 容器之外', () => {
    // canvas-graph 关闭后（</div>）紧跟 zoombar/connect-hint/MiniMap——
    // 它们不得嵌入 :style="graphStyle" 的容器（否则跟随平移缩放）
    const graphClose = vueSrc.indexOf('</div>\n\n        <!-- 缩放控制栏')
    expect(graphClose, '悬浮层应处于 canvas-graph 收尾之后').toBeGreaterThan(-1)
    const zoombarIdx = vueSrc.indexOf('class="canvas-zoombar"')
    const minimapIdx = vueSrc.indexOf('<MiniMap')
    expect(zoombarIdx).toBeGreaterThan(graphClose)
    expect(minimapIdx).toBeGreaterThan(graphClose)
    // 缩放栏让位小地图：bottom 需 >= 130px（mini 120 + 间隔）
    const zoombarCss = vueSrc.match(/\.canvas-zoombar\s*\{[^}]*\}/)![0]
    expect(zoombarCss).toMatch(/bottom:\s*(1[3-9]\d|\d{3,})px/)
  })
})

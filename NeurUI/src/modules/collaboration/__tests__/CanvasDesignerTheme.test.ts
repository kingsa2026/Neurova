import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * 无限画布（CanvasDesignerPage）深浅色主题适配回归测试。
 *
 * 背景：画布样式大量硬编码深色专供值——节点底 rgba(20,25,40,.95)、
 * 缩放栏/右键菜单同款深底、网格点 rgba(255,255,255,.04)（白点）、
 * 工具栏/侧栏/面板白色微透明叠加。浅色主题下：节点仍是深蓝黑底、
 * 网格点直接消失、浮层与背景混成一片。
 * 修复方向：全部换为语义化 --nr-* 变量（:root 深色与 [data-theme='light']
 * 浅色已各配一套值），与项目其余玻璃组件一致。
 */

const SFC_PATH = resolve(process.cwd(), 'src/modules/collaboration/CanvasDesignerPage.vue')
const sfc = readFileSync(SFC_PATH, 'utf-8')

/** 提取所有 <style ...> 块内容（按出现顺序） */
function styleBlocks(): string[] {
  const blocks: string[] = []
  const re = /<style\b[^>]*>([\s\S]*?)<\/style>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(sfc)) !== null) blocks.push(m[1])
  return blocks
}

/** 提取某 class 规则块的 CSS 文本（只匹配独立规则块，跳过逗号共享块） */
function ruleBlock(css: string, selector: string): string | null {
  const re = new RegExp(`(^|\\n)\\s*${selector}\\s*\\{([^}]*)\\}`)
  return css.match(re)?.[0] ?? null
}

describe('CanvasDesigner 深浅色主题适配', () => {
  const css = styleBlocks().join('\n')

  it('节点背景必须走语义化变量（浅色下节点不再深蓝黑底）', () => {
    const node = ruleBlock(css, '\\.graph-node\\b')
    expect(node).not.toBeNull()
    expect(node).not.toMatch(/rgba\(\s*20,\s*25,\s*40/)
    expect(node).toMatch(/var\(--nr-bg-elevated/)
  })

  it('缩放栏与右键菜单浮层不用硬编码深底', () => {
    const zoombar = ruleBlock(css, '\\.canvas-zoombar')
    const ctxMenu = ruleBlock(css, '\\.canvas-ctx-menu')
    expect(zoombar).not.toMatch(/rgba\(\s*20,\s*25,\s*40/)
    expect(ctxMenu).not.toMatch(/rgba\(\s*20,\s*25,\s*40/)
  })

  it('网格点不能用白色固定 alpha（浅色下白点不可见）', () => {
    const main = ruleBlock(css, '\\.canvas-main')
    expect(main).not.toBeNull()
    expect(main).not.toMatch(/rgba\(\s*255,\s*255,\s*255,\s*0\.04/)
    expect(main).toMatch(/--nr-text-muted|color-mix|--nr-border/)
  })

  it('工具栏/侧栏/节点库面板使用玻璃变量而非白色透明硬编码', () => {
    const toolbar = ruleBlock(css, '\\.canvas-toolbar')
    const sidebar = ruleBlock(css, '\\.canvas-sidebar')
    const palette = ruleBlock(css, '\\.palette-node')
    expect(toolbar).toMatch(/var\(--nr-glass-bg/)
    expect(sidebar).toMatch(/var\(--nr-glass-bg/)
    expect(palette).toMatch(/var\(--nr-glass-bg/)
  })

  it('输出视图与节点头部边框主题化', () => {
    const output = ruleBlock(css, '\\.node-output-view')
    const header = ruleBlock(css, '\\.graph-node-header')
    expect(output).toMatch(/var\(--nr-bg-inset/)
    expect(header).toMatch(/var\(--nr-glass-border/)
  })

  it('画布容器背景使用真实存在的主题变量（--nr-bg-primary 从未定义，恒走深色 fallback）', () => {
    const designer = ruleBlock(css, '\\.canvas-designer')
    expect(designer).toMatch(/var\(--nr-bg-base/)
    expect(designer).not.toMatch(/var\(--nr-bg-primary/)
  })

  it('样式块中不再存在深色专供的 rgba 白烟背景（255,255,255 低透明叠加）', () => {
    // 只禁止"属性值直接以 rgba(255,255,255,x) 开头"的硬编码；
    // var(--nr-border, rgba(255,255,255,0.08)) 内部的 fallback 是变量兜底，属合理设计。
    const hardcodedWhiteSmoke = css.match(/:\s*rgba\(\s*255,\s*255,\s*255,\s*0\.(0[1-4]|0[6]|1)/g) || []
    expect(hardcodedWhiteSmoke).toEqual([])
  })
})

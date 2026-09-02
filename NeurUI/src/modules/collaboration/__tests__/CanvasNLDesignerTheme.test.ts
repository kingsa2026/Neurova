import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * NL 画布设计器（右下角 AI 对话窗口）深浅色主题适配回归测试。
 *
 * 背景：nl-fab / nl-panel 硬编码深蓝黑底 rgba(20,22,40,.9/.96)、
 * agent 气泡硬编码白色微透明 rgba(255,255,255,.08)——浅色主题下
 * 窗口仍是深蓝黑块、白气泡在白底上消失、FAB 深底配深色文字不可读。
 * 修复方向：与画布主体一致换成语义化 --nr-* 变量。
 */

const SFC_PATH = resolve(process.cwd(), 'src/modules/collaboration/CanvasNLDesigner.vue')
const sfc = readFileSync(SFC_PATH, 'utf-8')

function styleBlocks(): string[] {
  const blocks: string[] = []
  const re = /<style\b[^>]*>([\s\S]*?)<\/style>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(sfc)) !== null) blocks.push(m[1])
  return blocks
}

function ruleBlock(css: string, selector: string): string | null {
  const re = new RegExp(`(^|\\n)\\s*${selector}\\s*\\{([^}]*)\\}`)
  return css.match(re)?.[0] ?? null
}

describe('CanvasNLDesigner 深浅色主题适配', () => {
  const css = styleBlocks().join('\n')

  it('面板与 FAB 背景必须走语义化变量（浅色下不再是深蓝黑块）', () => {
    const panel = ruleBlock(css, '\\.nl-panel')
    const fab = ruleBlock(css, '\\.nl-fab')
    expect(panel).not.toBeNull()
    expect(fab).not.toBeNull()
    expect(panel).not.toMatch(/rgba\(\s*20,\s*22,\s*40/)
    expect(fab).not.toMatch(/rgba\(\s*20,\s*22,\s*40/)
    expect(panel).toMatch(/var\(--nr-bg-elevated/)
    expect(fab).toMatch(/var\(--nr-bg-elevated/)
  })

  it('agent 气泡使用玻璃变量而非白烟硬编码（浅色下可见）', () => {
    const bubble = ruleBlock(css, '\\.nl-msg--agent \\.nl-bubble')
    expect(bubble).toMatch(/var\(--nr-glass-bg/)
    expect(bubble).not.toMatch(/rgba\(\s*255,\s*255,\s*255,\s*0\.0[0-9]/)
  })

  it('样式块中属性值不存在深色专供硬编码', () => {
    const hardcoded = css.match(/:\s*rgba\(\s*20,\s*22,\s*40/g) || []
    const whiteSmoke = css.match(/:\s*rgba\(\s*255,\s*255,\s*255,\s*0\.08/g) || []
    expect(hardcoded).toEqual([])
    expect(whiteSmoke).toEqual([])
  })
})

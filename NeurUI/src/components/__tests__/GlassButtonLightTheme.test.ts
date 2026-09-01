import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'

/**
 * 浅色主题按钮样式回归测试。
 *
 * 背景：GlassButton.vue 曾用 `:global([data-theme='light']) .nr-glass-btn--ghost ...`
 * 的 scoped 写法做浅色适配，但 @vue/compiler-sfc 3.5.x 会把 `:global(A) B` 编译成
 * 只有 A 的退化选择器（B 被丢弃），导致浅色覆盖规则命中 html[data-theme=light]、
 * 按钮本体永远收不到浅色样式（浅色模式下按钮仍是深蓝玻璃底）。
 * 因此必须断言：编译产物中主题规则的选择器链是完整的。
 */

// 与 themes.test.ts 一致：vitest 固定从 NeurUI 根目录启动
const SFC_PATH = resolve(process.cwd(), 'src/components/GlassButton.vue')
const sfc = readFileSync(SFC_PATH, 'utf-8')

/** 提取所有 <style ...>...</style> 块内容，按出现顺序返回 */
function extractStyleBlocks(source: string): Array<{ css: string; scoped: boolean }> {
  const blocks: Array<{ css: string; scoped: boolean }> = []
  const re = /<style\b([^>]*)>([\s\S]*?)<\/style>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) {
    blocks.push({ css: m[2], scoped: /\bscoped\b/.test(m[1]) })
  }
  return blocks
}

/** 编译出组件实际的全部 CSS（scoped 块带 data-v 处理，普通块原样） */
function compiledCss(): string {
  const blocks = extractStyleBlocks(sfc)
  return blocks
    .map(({ css, scoped }) =>
      compileStyle({
        source: css,
        filename: 'GlassButton.vue',
        id: 'data-v-test',
        scoped,
      }).code,
    )
    .join('\n')
}

describe('GlassButton 浅色主题规则编译完整性', () => {
  const allCss = compiledCss()

  it('编译产物中不再出现 :global( 残留（必须被编译器展开）', () => {
    expect(allCss).not.toContain(':global(')
    expect(allCss).not.toContain(':deep(')
  })

  it('ghost 浅色背景规则保留完整选择器链 [data-theme=light] .nr-glass-btn--ghost .nr-glass-btn-bg', () => {
    expect(allCss).toMatch(
      /\[data-theme='light'\][^{]*\.nr-glass-btn--ghost[^{]*\.nr-glass-btn-bg\s*\{/,
    )
  })

  it('secondary 浅色背景规则保留完整选择器链', () => {
    expect(allCss).toMatch(
      /\[data-theme='light'\][^{]*\.nr-glass-btn--secondary[^{]*\.nr-glass-btn-bg\s*\{/,
    )
  })

  it('浅色规则不能退化为独立的 [data-theme=light] 选择器（那会把样式打到 html 上）', () => {
    // 完整的浅色规则都要求含有 .nr-glass-btn--* 类；
    // 若出现 `[data-theme='light'] {` 形式的独立选择器即编译退化（bug）。
    const standalone = allCss.match(/\[data-theme='light'\]\s*\{/g) || []
    expect(standalone.length).toBe(0)
  })

  it('ghost hover 浅色规则同样保留完整链', () => {
    expect(allCss).toMatch(
      /\[data-theme='light'\][^{]*\.nr-glass-btn--ghost[^{]*:hover[^{]*\.nr-glass-btn-bg\s*\{/,
    )
  })
})

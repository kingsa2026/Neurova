/**
 * 主题系统契约测试
 *
 * 两套主题:
 *  1. Cosmic（深色）— 现有 UI 风格，定义在 :root，必须原样保留
 *  2. Light（浅色）— 参照 DeepSeek 风格的简洁浅色主题，定义在 [data-theme='light']
 *
 * 所有颜色类令牌必须在浅色主题中提供覆盖，保证全站无硬编码色值穿透。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// vitest 的 CSS 插件会吞掉 ?raw 导入，这里直接读源文件做契约校验
// （vitest 固定从 NeurUI 根目录启动，见 package.json "test": "vitest"）
const variablesCss = readFileSync(
  resolve(process.cwd(), 'src/styles/variables.css'),
  'utf-8',
).replace(/\/\*[\s\S]*?\*\//g, '') // 剥离注释，避免注释中的选择器文本干扰解析

/** 提取指定选择器的规则块内容（支持嵌套大括号）。 */
function blockOf(css: string, selector: string): string {
  const start = css.indexOf(selector)
  if (start === -1) return ''
  const braceStart = css.indexOf('{', start)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < css.length; i++) {
    if (css[i] === '{') depth++
    else if (css[i] === '}') {
      depth--
      if (depth === 0) return css.slice(braceStart + 1, i)
    }
  }
  return ''
}

/** 从规则块中取某个 CSS 变量的值。 */
function valueOf(block: string, name: string): string {
  const re = new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*:\\s*([^;]+);`)
  const m = block.match(re)
  return m ? m[1].trim() : ''
}

const rootBlock = blockOf(variablesCss, ':root')
const lightBlock = blockOf(variablesCss, "[data-theme='light']")

/** 颜色相关令牌：浅色主题必须全部覆盖（结构类令牌如间距/圆角/字体无需覆盖）。 */
const COLOR_TOKENS = [
  '--nr-bg-deep',
  '--nr-bg-base',
  '--nr-bg-surface',
  '--nr-bg-elevated',
  '--nr-bg-overlay',
  '--nr-bg-inset',
  '--nr-bg-inset-deep',
  '--nr-glass-rgb',
  '--nr-glass-bg',
  '--nr-glass-bg-hover',
  '--nr-glass-bg-active',
  '--nr-glass-border',
  '--nr-glass-border-hover',
  '--nr-primary',
  '--nr-primary-light',
  '--nr-primary-dark',
  '--nr-accent',
  '--nr-accent-secondary',
  '--nr-gradient-primary',
  '--nr-gradient-accent',
  '--nr-text-primary',
  '--nr-text-secondary',
  '--nr-text-tertiary',
  '--nr-text-muted',
  '--nr-success',
  '--nr-warning',
  '--nr-error',
  '--nr-info',
  '--nr-border',
  '--nr-border-light',
  '--nr-shadow-sm',
  '--nr-shadow-md',
  '--nr-shadow-lg',
  '--nr-shadow-glow',
  '--nr-primary-soft',
  '--nr-primary-soft-border',
  '--nr-primary-ring',
  '--nr-header-bg',
  '--nr-sidebar-bg',
  '--nr-bubble-user',
  '--nr-bubble-user-border',
  '--nr-panel-shadow',
]

describe('Cosmic 深色主题（:root，现有风格必须保留）', () => {
  it(':root 块存在', () => {
    expect(rootBlock).not.toBe('')
  })

  it('保留宇宙深空背景色', () => {
    expect(valueOf(rootBlock, '--nr-bg-deep')).toBe('#06080f')
    expect(valueOf(rootBlock, '--nr-bg-base')).toBe('#0a0e1a')
    expect(valueOf(rootBlock, '--nr-bg-surface')).toBe('#111827')
    expect(valueOf(rootBlock, '--nr-bg-elevated')).toBe('#1a2236')
  })

  it('保留品牌主色与强调色', () => {
    expect(valueOf(rootBlock, '--nr-primary')).toBe('#6366f1')
    expect(valueOf(rootBlock, '--nr-primary-light')).toBe('#818cf8')
    expect(valueOf(rootBlock, '--nr-accent')).toBe('#22d3ee')
  })

  it('保留白色玻璃拟态令牌', () => {
    expect(valueOf(rootBlock, '--nr-glass-rgb')).toMatch(/^255,\s*255,\s*255$/)
    expect(valueOf(rootBlock, '--nr-glass-bg')).toMatch(/rgba\(255,\s*255,\s*255/)
    expect(valueOf(rootBlock, '--nr-glass-border')).toMatch(/rgba\(255,\s*255,\s*255/)
  })

  it('新增兼容令牌在深色主题中有定义', () => {
    for (const token of [
      '--nr-glass-bg-active',
      '--nr-bg-inset',
      '--nr-bg-inset-deep',
      '--nr-primary-soft',
      '--nr-primary-soft-border',
      '--nr-primary-ring',
      '--nr-header-bg',
      '--nr-bubble-user',
      '--nr-bubble-user-border',
      '--nr-panel-shadow',
    ]) {
      expect(valueOf(rootBlock, token), `${token} 应在 :root 中定义`).not.toBe('')
    }
  })
})

describe('Light 浅色主题（DeepSeek 风格）', () => {
  it("[data-theme='light'] 块存在", () => {
    expect(lightBlock).not.toBe('')
  })

  it('使用 DeepSeek 蓝作为主色', () => {
    expect(valueOf(lightBlock, '--nr-primary')).toBe('#4d6bfe')
  })

  it('使用浅灰白背景（简洁大方）', () => {
    expect(valueOf(lightBlock, '--nr-bg-deep')).toBe('#f5f6f7')
    expect(valueOf(lightBlock, '--nr-bg-surface')).toBe('#ffffff')
  })

  it('正文使用深色墨迹文字，保证对比度', () => {
    expect(valueOf(lightBlock, '--nr-text-primary')).toMatch(/rgba\(31,\s*35,\s*41/)
    expect(valueOf(lightBlock, '--nr-text-secondary')).toMatch(/rgba\(31,\s*35,\s*41/)
  })

  it('玻璃令牌使用深色半透明叠加（白底可见）', () => {
    expect(valueOf(lightBlock, '--nr-glass-rgb')).toMatch(/^31,\s*35,\s*41$/)
    expect(valueOf(lightBlock, '--nr-glass-bg')).toMatch(/rgba\(31,\s*35,\s*41/)
    expect(valueOf(lightBlock, '--nr-glass-border')).toMatch(/rgba\(31,\s*35,\s*41/)
  })

  it('阴影为轻柔的浅色系阴影', () => {
    expect(valueOf(lightBlock, '--nr-shadow-lg')).toMatch(/rgba\(31,\s*35,\s*41/)
  })

  it('所有颜色令牌在浅色主题中均有覆盖', () => {
    const missing = COLOR_TOKENS.filter((t) => valueOf(lightBlock, t) === '')
    expect(missing).toEqual([])
  })
})

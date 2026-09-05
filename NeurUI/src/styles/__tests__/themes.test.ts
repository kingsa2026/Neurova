/**
 * 主题系统契约测试
 *
 * 两套主题（2026-09-05 起切换为 Apple iOS Liquid Glass 风格）:
 *  1. iOS 深色 — 定义在 :root（纯黑背景、iOS SystemGray 表面、Accent 蓝 #0a84ff）
 *  2. iOS 浅色 — 定义在 [data-theme='light']（systemGroupedBackground #f2f2f7、
 *     白色表面、Accent 蓝 #007aff）
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

describe('iOS 深色主题（:root）', () => {
  it(':root 块存在', () => {
    expect(rootBlock).not.toBe('')
  })

  it('使用 iOS 纯黑系统背景', () => {
    expect(valueOf(rootBlock, '--nr-bg-deep')).toBe('#000000')
    expect(valueOf(rootBlock, '--nr-bg-base')).toBe('#000000')
    expect(valueOf(rootBlock, '--nr-bg-surface')).toBe('#1c1c1e')
    expect(valueOf(rootBlock, '--nr-bg-elevated')).toBe('#2c2c2e')
  })

  it('使用 iOS Accent 蓝（深色 #0a84ff）与 Cyan 强调色', () => {
    expect(valueOf(rootBlock, '--nr-primary')).toBe('#0a84ff')
    expect(valueOf(rootBlock, '--nr-primary-light')).toBe('#409cff')
    expect(valueOf(rootBlock, '--nr-accent')).toBe('#64d2ff')
  })

  it('保留白色玻璃拟态令牌（Liquid Glass 材质）', () => {
    expect(valueOf(rootBlock, '--nr-glass-rgb')).toMatch(/^255,\s*255,\s*255$/)
    expect(valueOf(rootBlock, '--nr-glass-bg')).toMatch(/rgba\(255,\s*255,\s*255/)
    expect(valueOf(rootBlock, '--nr-glass-border')).toMatch(/rgba\(255,\s*255,\s*255/)
  })

  it('状态色使用 iOS 系统色（深色模式）,文本使用白色标签分层', () => {
    expect(valueOf(rootBlock, '--nr-success')).toBe('#30d158')
    expect(valueOf(rootBlock, '--nr-warning')).toBe('#ff9f0a')
    expect(valueOf(rootBlock, '--nr-error')).toBe('#ff453a')
    expect(valueOf(rootBlock, '--nr-text-primary')).toMatch(/rgba\(255,\s*255,\s*255/)
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

describe('iOS 浅色主题（Liquid Glass light）', () => {
  it("[data-theme='light'] 块存在", () => {
    expect(lightBlock).not.toBe('')
  })

  it('使用 iOS Accent 蓝作为主色', () => {
    expect(valueOf(lightBlock, '--nr-primary')).toBe('#007aff')
  })

  it('使用 systemGroupedBackground 浅灰白背景', () => {
    expect(valueOf(lightBlock, '--nr-bg-deep')).toBe('#f2f2f7')
    expect(valueOf(lightBlock, '--nr-bg-surface')).toBe('#ffffff')
  })

  it('正文使用纯黑标签文字，保证对比度', () => {
    expect(valueOf(lightBlock, '--nr-text-primary')).toMatch(/rgba\(0,\s*0,\s*0/)
    expect(valueOf(lightBlock, '--nr-text-secondary')).toMatch(/rgba\(0,\s*0,\s*0/)
  })

  it('玻璃令牌使用 iOS SystemGray（120,120,128）半透明叠加', () => {
    expect(valueOf(lightBlock, '--nr-glass-rgb')).toMatch(/^120,\s*120,\s*128$/)
    expect(valueOf(lightBlock, '--nr-glass-bg')).toMatch(/rgba\(120,\s*120,\s*128/)
    expect(valueOf(lightBlock, '--nr-glass-border')).toMatch(/rgba\(60,\s*60,\s*67/)
  })

  it('阴影为轻柔的黑色系阴影（白色玻璃投影）', () => {
    expect(valueOf(lightBlock, '--nr-shadow-lg')).toMatch(/rgba\(0,\s*0,\s*0/)
  })

  it('所有颜色令牌在浅色主题中均有覆盖', () => {
    const missing = COLOR_TOKENS.filter((t) => valueOf(lightBlock, t) === '')
    expect(missing).toEqual([])
  })
})
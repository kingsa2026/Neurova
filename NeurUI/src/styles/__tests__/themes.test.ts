/**
 * 主题系统契约测试 — 双皮肤 × 双明暗
 *
 * 皮肤（Skins）:
 *  1. cosmic — 原版星空玻璃拟态（默认皮肤）
 *     深色: :root[data-skin='cosmic']（星云紫 #6366f1 渐变）
 *     浅色: :root[data-skin='cosmic'][data-theme='light']（DeepSeek 白底蓝 #4d6bfe）
 *  2. ios — Apple iOS 20 Liquid Glass
 *     深色: :root[data-skin='ios']（Accent 蓝 #0a84ff、纯黑背景）
 *     浅色: :root[data-skin='ios'][data-theme='light']（#007aff、systemGroupedBackground #f2f2f7）
 *
 * 所有颜色类令牌必须在对应皮肤的浅色主题中提供覆盖，
 * 保证全站无硬编码色值穿透。
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
const globalCss = readFileSync(
  resolve(process.cwd(), 'src/styles/global.css'),
  'utf-8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 提取指定选择器的规则块内容（支持嵌套大括号，拒绝前缀误匹配）。 */
function blockOf(css: string, selector: string): string {
  let idx = 0
  while ((idx = css.indexOf(selector, idx)) !== -1) {
    const braceStart = css.indexOf('{', idx)
    if (braceStart === -1) return ''
    // 选择器与 `{` 之间必须无其他字符——避免长选择器（如
    // '[data-skin=\"ios\"][data-theme=\"light\"]'）前缀匹配到短选择器
    if (css.slice(idx + selector.length, braceStart).trim() !== '') {
      idx = braceStart
      continue
    }
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
  return ''
}

/** 从规则块中取某个 CSS 变量的值。 */
function valueOf(block: string, name: string): string {
  const re = new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*:\\s*([^;]+);`)
  const m = block.match(re)
  return m ? m[1].trim() : ''
}

const SKINS = {
  cosmicDark: ":root[data-skin='cosmic']",
  cosmicLight: ":root[data-skin='cosmic'][data-theme='light']",
  iosDark: ":root[data-skin='ios']",
  iosLight: ":root[data-skin='ios'][data-theme='light']",
} as const

const cosmicDark = blockOf(variablesCss, SKINS.cosmicDark)
const cosmicLight = blockOf(variablesCss, SKINS.cosmicLight)
const iosDark = blockOf(variablesCss, SKINS.iosDark)
const iosLight = blockOf(variablesCss, SKINS.iosLight)

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

describe('双皮肤共存架构', () => {
  it('四个皮肤×明暗选择器块全部存在', () => {
    expect(cosmicDark).not.toBe('')
    expect(cosmicLight).not.toBe('')
    expect(iosDark).not.toBe('')
    expect(iosLight).not.toBe('')
  })
})

describe('Cosmic 皮肤（原版）· 深色', () => {
  it('使用星云黑背景与紫色渐变品牌色', () => {
    expect(valueOf(cosmicDark, '--nr-bg-deep')).toBe('#06080f')
    expect(valueOf(cosmicDark, '--nr-bg-surface')).toBe('#111827')
    expect(valueOf(cosmicDark, '--nr-primary')).toBe('#6366f1')
    expect(valueOf(cosmicDark, '--nr-accent')).toBe('#22d3ee')
  })

  it('玻璃令牌使用白色半透明叠加', () => {
    expect(valueOf(cosmicDark, '--nr-glass-rgb')).toMatch(/^255,\s*255,\s*255$/)
    expect(valueOf(cosmicDark, '--nr-glass-bg')).toMatch(/rgba\(255,\s*255,\s*255/)
  })

  it('使用 DM Sans 字体栈与小圆角结构令牌', () => {
    expect(valueOf(cosmicDark, '--nr-font-body')).toContain('DM Sans')
    expect(valueOf(cosmicDark, '--nr-radius-md')).toBe('10px')
  })
})

describe('Cosmic 皮肤（原版）· 浅色', () => {
  it('使用 DeepSeek 白底与 #4d6bfe 品牌蓝', () => {
    expect(valueOf(cosmicLight, '--nr-bg-deep')).toBe('#f5f6f7')
    expect(valueOf(cosmicLight, '--nr-bg-surface')).toBe('#ffffff')
    expect(valueOf(cosmicLight, '--nr-primary')).toBe('#4d6bfe')
  })

  it('正文使用深色墨迹文字', () => {
    expect(valueOf(cosmicLight, '--nr-text-primary')).toMatch(/rgba\(31,\s*35,\s*41/)
  })

  it('所有颜色令牌在 cosmic 浅色中均有覆盖', () => {
    const missing = COLOR_TOKENS.filter((t) => valueOf(cosmicLight, t) === '')
    expect(missing).toEqual([])
  })
})

describe('iOS 皮肤（Liquid Glass）· 深色', () => {
  it('使用 iOS Accent 蓝与纯黑系统背景', () => {
    expect(valueOf(iosDark, '--nr-bg-deep')).toBe('#000000')
    expect(valueOf(iosDark, '--nr-bg-surface')).toBe('#1c1c1e')
    expect(valueOf(iosDark, '--nr-primary')).toBe('#0a84ff')
    expect(valueOf(iosDark, '--nr-accent')).toBe('#64d2ff')
  })

  it('状态色使用 iOS 系统色（深色模式）', () => {
    expect(valueOf(iosDark, '--nr-success')).toBe('#30d158')
    expect(valueOf(iosDark, '--nr-warning')).toBe('#ff9f0a')
    expect(valueOf(iosDark, '--nr-error')).toBe('#ff453a')
  })

  it('使用 SF Pro 字体栈与大圆角结构令牌', () => {
    expect(valueOf(iosDark, '--nr-font-body')).toContain('SF Pro')
    expect(valueOf(iosDark, '--nr-radius-md')).toBe('14px')
  })
})

describe('iOS 皮肤（Liquid Glass）· 浅色', () => {
  it('使用 iOS 浅色 Accent 蓝 #007aff 与 systemGroupedBackground', () => {
    expect(valueOf(iosLight, '--nr-primary')).toBe('#007aff')
    expect(valueOf(iosLight, '--nr-bg-deep')).toBe('#f2f2f7')
    expect(valueOf(iosLight, '--nr-bg-surface')).toBe('#ffffff')
  })

  it('玻璃令牌使用 iOS SystemGray（120,120,128）半透明叠加', () => {
    expect(valueOf(iosLight, '--nr-glass-rgb')).toMatch(/^120,\s*120,\s*128$/)
    expect(valueOf(iosLight, '--nr-glass-bg')).toMatch(/rgba\(120,\s*120,\s*128/)
  })

  it('所有颜色令牌在 ios 浅色中均有覆盖', () => {
    const missing = COLOR_TOKENS.filter((t) => valueOf(iosLight, t) === '')
    expect(missing).toEqual([])
  })
})

describe('Liquid Glass 高光还原契约（iOS 26 玻璃材质标志性特征）', () => {
  /** 提取 rgba 的 alpha 数值。 */
  const alpha = (color: string): number =>
    Number(color.match(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)/)?.[1] ?? 0)

  it('四块皮肤均须定义玻璃高光顶点令牌（--nr-glass-specular-top）', () => {
    for (const block of [cosmicDark, cosmicLight, iosDark, iosLight]) {
      expect(valueOf(block, '--nr-glass-specular-top'), '任一皮肤缺高光描边令牌').not.toBe('')
    }
  })

  it('iOS 皮肤顶部高光描边强度须显著高于 cosmic（cosmic 保持原版低调观感）', () => {
    // Liquid Glass 标志性 1px 白色边缘高光；cosmic 只保留极弱光泽
    expect(alpha(valueOf(iosDark, '--nr-glass-specular-top'))).toBeGreaterThan(
      alpha(valueOf(cosmicDark, '--nr-glass-specular-top')) + 0.4,
    )
    expect(alpha(valueOf(iosLight, '--nr-glass-specular-top'))).toBeGreaterThan(
      alpha(valueOf(cosmicLight, '--nr-glass-specular-top')) + 0.4,
    )
  })

  it('四块皮肤均须定义内部折射光斑令牌（--nr-glass-highlight）', () => {
    for (const block of [cosmicDark, cosmicLight, iosDark, iosLight]) {
      expect(valueOf(block, '--nr-glass-highlight'), '任一皮肤缺内部折射光斑令牌').not.toBe('')
    }
  })

  it('iOS 皮肤内部光斑须为白色高光（折射亮斑），cosmic 可为弱白', () => {
    expect(valueOf(iosDark, '--nr-glass-highlight')).toMatch(/rgba\(255/)
    expect(valueOf(cosmicDark, '--nr-glass-highlight')).not.toBe('')
  })

  it('iOS 皮肤下氛围壁纸提供彩色透射（star-bg 彩色光晕覆盖）', () => {
    // 玻璃背后必须有真实彩色壁纸让材质"染色"，纯黑/纯白背景无法体现玻璃折射
    const iosStarBg = globalCss.match(/\[data-skin='ios'\][^{]*\.star-bg\s*\{([^}]*)\}/)?.[1] ?? ''
    expect(iosStarBg, '缺 data-skin=ios 的 star-bg 壁纸覆盖').not.toBe('')
    expect(iosStarBg).toMatch(/rgba\(/)
    expect(iosStarBg).not.toMatch(/transparent\s*\)\s*,\s*var\(--nr-bg-deep\)\s*$/)
  })
})
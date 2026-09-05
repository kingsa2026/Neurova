/**
 * ant-tabs 玻璃胶囊统一契约测试（2026-09-05 全站页签样式统一）。
 *
 * 背景：页面级导航（AgentPageTabs 胶囊玻璃风）与页内切换（13 个页面的
 * a-tabs 默认下划线风）视觉割裂。统一策略：global.css 中把 ant-tabs
 * 主题化为与 .nr-page-tab 同源的胶囊风——隐藏 ink-bar、激活页签
 * primary-soft 胶囊底、nav 去底线。顶/左双布局（SettingPage 用 left）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// vitest 固定从 NeurUI 根目录启动；剥离注释避免选择器文本误匹配
const globalCss = readFileSync(
  resolve(process.cwd(), 'src/styles/global.css'),
  'utf-8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 提取首个匹配 selector 前缀的规则块（容忍选择器尾部逗号分组/后代）。 */
function findBlock(selectorSubstring: string): string {
  const re = /([^{}]+)\{([^{}]*)\}/g
  let m: RegExpExecArray | null
  while ((m = re.exec(globalCss)) !== null) {
    if (m[1].includes(selectorSubstring)) return m[2]
  }
  return ''
}

describe('ant-tabs 玻璃胶囊统一（global.css）', () => {
  it('ink-bar 必须隐藏（胶囊态的下划线指示器已无意义）', () => {
    const block = findBlock('.ant-tabs-ink-bar')
    expect(block).toContain('display: none')
  })

  it('tab 激活态必须是 primary-soft 胶囊（与 AgentPageTabs is-active 同源）', () => {
    // 用复合选择器子串精确匹配胶囊规则（避开 .ant-tabs-tab-active .ant-tabs-tab-btn 字色规则）
    // 圆角由常态 .ant-tabs-tab 提供（同一元素），激活块只负责底色+描边
    const block = findBlock('.ant-tabs-tab.ant-tabs-tab-active')
    expect(block).toContain('var(--nr-primary-soft)')
    expect(block).toContain('var(--nr-primary-soft-border)')
  })

  it('tab 常态用次级文字色、hover 玻璃提亮（胶囊悬停反馈）', () => {
    const hover = findBlock('.ant-tabs-tab:hover')
    expect(hover).toContain('var(--nr-glass-bg-hover)')
    expect(findBlock('.ant-tabs-tab')).toContain('var(--nr-text-secondary)')
  })

  it('nav 容器玻璃胶囊底 + 去底线（顶/左双布局都要去）', () => {
    expect(findBlock('.ant-tabs-nav')).toContain('var(--nr-glass-bg)')
    // ::before 是 antd 画底线/竖线的伪元素，两种布局都来自它
    const before = findBlock('.ant-tabs-nav::before')
    expect(before).toContain('none')
  })

  it('tab 间距与圆角与 AgentPageTabs 对齐（gap 4 / 圆角 9）', () => {
    const tab = findBlock('.ant-tabs-tab')
    expect(tab).toContain('border-radius: 9px')
  })

  it('全站不得再保留 ink-bar 着色规则（胶囊态已隐藏，避免死样式）', () => {
    expect(globalCss).not.toMatch(/\.ant-tabs-ink-bar\s*\{[^}]*background:/)
  })
})

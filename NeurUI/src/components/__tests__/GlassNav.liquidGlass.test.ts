/**
 * GlassNav 品牌区/底部区液态玻璃背景契约测试
 *
 * 需求（2026-09-16）: 左上角 logo 区与底部用户头像区的背景做成液态玻璃效果，
 * 与登录页液态效果保持一致 —— 登录页定案参数为 GlassSurface
 * radius 27 / backgroundOpacity 0.12 / displace 0.5（官方 live demo 字面值，
 * 经 /glass-demo 三变量对照实拍定案，见 LoginPage.vue 注释）。
 *
 * 契约:
 *   1. 品牌区与底部区各被一个 GlassSurface 包裹（.nr-glass-surface）。
 *   2. 两处 GlassSurface 参数与登录页一致：width 100% / height auto /
 *      borderRadius 27 / backgroundOpacity 0.12 / displace 0.5，
 *      padding 0（内边距由品牌区/页脚内容自带，避免双重叠加）。
 *   3. 参数单源：与 LoginPage.vue 中 GlassSurface 的覆写值保持一致
 *      （若登录页参数调整，此测试会红，强制两处同步）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import GlassNav from '../GlassNav.vue'
import GlassSurface from '../GlassSurface.vue'

// 编译 GlassNav 实际 CSS（scoped 块带 data-v 处理），供布局契约断言
const navSfc = readFileSync(resolve(process.cwd(), 'src/components/GlassNav.vue'), 'utf-8')
const navCss = [...navSfc.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)]
  .map(([, attrs, body]) =>
    compileStyle({ source: body, filename: 'GlassNav.vue', id: 'data-v-test', scoped: /\bscoped\b/.test(attrs) }).code,
  )
  .join('\n')

/** 取某选择器第一条规则的声明体（scoped 编译后类名后跟 [data-v-*]，需容忍） */
function ruleBody(css: string, selector: string): string {
  const m = css.match(new RegExp(`\\.${selector}(?:\\[[^\\]]*\\])*\\s*\\{([^}]*)\\}`))
  expect(m, `编译产物中应存在 .${selector} 规则`).not.toBeNull()
  return m![1]
}

function mountNavWithFooter() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(GlassNav, {
    props: {},
    slots: { footer: '<div class="test-footer-user">user</div>' },
    global: { plugins: [pinia] },
  })
}

describe('GlassNav · 品牌区/底部区液态玻璃（与登录页同参数）', () => {
  it('品牌区与底部区各被一个 GlassSurface 包裹', () => {
    const wrapper = mountNavWithFooter()
    const surfaces = wrapper.findAllComponents(GlassSurface)
    expect(surfaces.length).toBe(2)
    // 品牌区在第一个 surface 内，页脚内容在第二个内
    expect(wrapper.find('.nr-glass-nav-brand').element.closest('.nr-glass-surface')).not.toBeNull()
    expect(wrapper.find('.test-footer-user').element.closest('.nr-glass-surface')).not.toBeNull()
  })

  it('两处 surface 参数 = 登录页定案值（100%/auto/27/0.12/0.5/padding 0）', () => {
    const wrapper = mountNavWithFooter()
    for (const surface of wrapper.findAllComponents(GlassSurface)) {
      expect(surface.props('width')).toBe('100%')
      expect(surface.props('height')).toBe('auto')
      expect(surface.props('borderRadius')).toBe(27)
      expect(surface.props('backgroundOpacity')).toBe(0.12)
      expect(surface.props('displace')).toBe(0.5)
      expect(surface.props('padding')).toBe('0')
    }
  })

  it('参数单源守卫：LoginPage.vue 仍使用同一组覆写值', () => {
    const login = readFileSync(resolve(process.cwd(), 'src/pages/LoginPage.vue'), 'utf-8')
    expect(login).toMatch(/:border-radius="27"/)
    expect(login).toMatch(/:background-opacity="0\.12"/)
    expect(login).toMatch(/:displace="0\.5"/)
  })
})

/**
 * 折射渗透契约（2026-09-16 第二轮）: 菜单文字滚动时必须穿过玻璃面板背后。
 * 实现 = 菜单区负 margin 上/下延伸进品牌区/底部区 + 等量 padding 保持首尾项
 * 初始不被遮挡；玻璃面板 position: relative + z-index 抬到文字之上。
 */
describe('GlassNav · 菜单文字折射穿过玻璃（渗透区布局）', () => {
  it('品牌区/底部区 surface 悬浮于菜单文字之上（relative + z-index ≥ 2）', () => {
    for (const sel of ['nr-glass-nav-brand-surface', 'nr-glass-nav-footer-surface']) {
      const body = ruleBody(navCss, sel)
      expect(body, `.${sel} 应 position: relative`).toMatch(/position:\s*relative/)
      const z = body.match(/z-index:\s*(\d+)/)
      expect(z, `.${sel} 应设 z-index`).not.toBeNull()
      expect(Number(z![1])).toBeGreaterThanOrEqual(2)
    }
  })

  it('菜单区上/下渗透（负 margin 延伸 + 等量 padding 预留）', () => {
    const body = ruleBody(navCss, 'nr-glass-nav-items')
    expect(body).toMatch(/margin-top:\s*calc\(\s*var\([^)]+\)\s*\*\s*-1\s*\)/)
    expect(body).toMatch(/padding-top:\s*var\(/)
    expect(body).toMatch(/margin-bottom:\s*calc\(\s*var\([^)]+\)\s*\*\s*-1\s*\)/)
    expect(body).toMatch(/padding-bottom:\s*var\(/)
  })

  it('渗透量以 CSS 变量单源定义，且折叠态另有收窄值', () => {
    expect(navCss).toMatch(/--nr-nav-brand-bleed:\s*\d+px/)
    expect(navCss).toMatch(/--nr-nav-footer-bleed:\s*\d+px/)
    // 折叠态品牌/底部更矮，渗透量必须同步收窄，否则露出无玻璃的文字带
    const collapsed = navCss.match(/\.nr-glass-nav\.is-collapsed(?:\[[^\]]*\])*\s*\{([^}]*)\}/)
    expect(collapsed, '应存在折叠态渗透量覆写规则').not.toBeNull()
    expect(collapsed![1]).toMatch(/--nr-nav-brand-bleed:\s*\d+px/)
    expect(collapsed![1]).toMatch(/--nr-nav-footer-bleed:\s*\d+px/)
  })
})

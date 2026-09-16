/**
 * BrandLogo 品牌区组件契约测试（双皮肤共用原版图片 logo × 深浅色适配）
 *
 * 需求（2026-09-05）: iOS 皮肤同样沿用原版 NEUROVA 图片 logo，
 * 不渲染独立玻璃字标 —— 深浅色由图片资源切换适配（深色 white / 浅色 black）。
 *
 * 契约:
 *   1. 一切皮肤（cosmic / ios）均渲染图片 logo，且跟随深浅色切换
 *      深色 → NEUROVA-LOGO350white.png / 浅色 → NEUROVA-LOGO350black.png。
 *   2. 皮肤切换不影响品牌渲染（品牌视觉与皮肤无关）。
 *   3. collapsed 时图片缩小；size=lg（认证页）渲染大图。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import BrandLogo from '../BrandLogo.vue'
import { useAppStore } from '@/stores/app'

function mountLogo(skin: 'cosmic' | 'ios', theme: 'dark' | 'light' = 'dark', collapsed = false, size: 'sm' | 'lg' = 'sm') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAppStore()
  store.setSkin(skin)
  store.setTheme(theme)
  return mount(BrandLogo, {
    props: { collapsed, size },
    global: { plugins: [pinia] },
  })
}

describe('BrandLogo · 深浅色图片适配（两套皮肤共用原版 logo）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-skin')
    document.documentElement.removeAttribute('data-theme')
  })

  it('cosmic 深色渲染白色图片', () => {
    const wrapper = mountLogo('cosmic', 'dark')
    const img = wrapper.find('img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toContain('NEUROVA-LOGO350white.png')
  })

  it('cosmic 浅色渲染黑色图片', () => {
    const wrapper = mountLogo('cosmic', 'light')
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350black.png')
  })

  it('ios 深色同样渲染白色图片（沿用原版 logo）', () => {
    const wrapper = mountLogo('ios', 'dark')
    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350white.png')
  })

  it('ios 浅色同样渲染黑色图片（深浅色随主题切换）', () => {
    const wrapper = mountLogo('ios', 'light')
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350black.png')
  })

  it('切换深浅色后 src 由 white 切为 black', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAppStore()
    store.setSkin('ios')
    store.setTheme('dark')
    const wrapper = mount(BrandLogo, { props: {}, global: { plugins: [pinia] } })
    expect(wrapper.find('img').attributes('src')).toContain('white.png')
    store.setTheme('light')
    await nextTick()
    expect(wrapper.find('img').attributes('src')).toContain('black.png')
  })
})

describe('BrandLogo · 形态（折叠 / 认证页大标）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-skin')
    document.documentElement.removeAttribute('data-theme')
  })

  it('collapsed 时图片带 is-collapsed 类（缩小）', () => {
    const wrapper = mountLogo('ios', 'dark', true)
    expect(wrapper.find('img').classes()).toContain('is-collapsed')
  })

  it('size=lg 渲染大图（认证页），根节点带 lg 标记', () => {
    const wrapper = mountLogo('cosmic', 'dark', false, 'lg')
    expect(wrapper.find('.nr-brand').classes()).toContain('nr-brand--lg')
    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350white.png')
  })

  it('size=lg + ios 皮肤同样渲染图片大标', () => {
    const wrapper = mountLogo('ios', 'light', false, 'lg')
    expect(wrapper.find('.nr-brand').classes()).toContain('nr-brand--lg')
    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350black.png')
  })
})

describe('BrandLogo · 侧栏 logo 尺寸（2026-09-16 调大需求）', () => {
  // 对齐 GlassButtonLightTheme 先例：编译 SFC 样式断言产物
  const sfc = readFileSync(resolve(process.cwd(), 'src/components/BrandLogo.vue'), 'utf-8')
  const css = [...sfc.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)]
    .map(([, attrs, body]) =>
      compileStyle({ source: body, filename: 'BrandLogo.vue', id: 'data-v-test', scoped: /\bscoped\b/.test(attrs) }).code,
    )
    .join('\n')

  // 图片资源 350×90（宽高比 ≈ 3.89），max-width 小于 height×比例 会裁掉宽度
  const ASPECT = 350 / 90
  // scoped 编译后类名后跟 [data-v-*]，选择器与 { 之间需容忍属性后缀
  const IMG_RULE = /\.nr-brand-logo-img(?:\[[^\]]*\])*\s*\{([^}]*)\}/

  it('展开态 height ≥ 38px（比旧值 30px 明显调大）', () => {
    const body = css.match(IMG_RULE)
    expect(body, '应存在 .nr-brand-logo-img 规则').not.toBeNull()
    const h = body![1].match(/height:\s*(\d+(?:\.\d+)?)px/)
    expect(h, '规则应含 height 声明').not.toBeNull()
    expect(Number(h![1])).toBeGreaterThanOrEqual(38)
  })

  it('max-width 不裁切等比宽度（≥ height × 3.89，侧栏 240px 内安全）', () => {
    const body = css.match(IMG_RULE)![1]
    const h = Number(body.match(/height:\s*(\d+(?:\.\d+)?)px/)![1])
    const w = Number(body.match(/max-width:\s*(\d+(?:\.\d+)?)px/)![1])
    expect(w).toBeGreaterThanOrEqual(Math.ceil(h * ASPECT))
    // 侧栏 240px − content padding 24 − brand padding 20 = 196px 可用宽
    expect(w).toBeLessThanOrEqual(196)
  })

  // 折叠态契约（2026-09-16）: 仅显示罗盘图形 —— 原图 350×90 中图形占 x∈[0,94]，
  // 用 cover + 左对齐裁出图形区（34×32 盒显示原图 x∈[0,95.6]，完整含 94px 右缘横杆）。
  it('折叠态裁剪为纯图形（cover + 左对齐，非整图缩略）', () => {
    const m = css.match(/\.nr-brand-logo-img\.is-collapsed(?:\[[^\]]*\])*\s*\{([^}]*)\}/)
    expect(m, '应存在折叠态规则').not.toBeNull()
    const body = m![1]
    expect(body).toMatch(/object-fit:\s*cover/)
    expect(body).toMatch(/object-position:\s*left/)
    // 宽高比须 ≥ 94/90 才能完整露出图形右缘
    const w = Number(body.match(/width:\s*(\d+(?:\.\d+)?)px/)![1])
    const h = Number(body.match(/height:\s*(\d+(?:\.\d+)?)px/)![1])
    expect(w / h).toBeGreaterThanOrEqual(94 / 90)
    // 折叠侧栏 64px − content padding 24 = 40px 可用宽
    expect(w).toBeLessThanOrEqual(40)
  })
})
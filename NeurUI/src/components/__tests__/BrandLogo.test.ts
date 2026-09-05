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
/**
 * GlassNav 默认品牌槽契约测试（防回归）
 *
 * 根因（2026-09-05）: 品牌渲染契约曾被复制到 GlassNav 默认槽，
 * 按 appStore.isDark 换黑白图 —— 与 BrandLogo 出现双实现。
 *
 * 契约:
 *   1. 未传 #brand 时, 默认槽必须渲染 BrandLogo（两套皮肤均渲染原版图片 logo,
 *      深浅色由图片资源切换）。
 *   2. 传 #brand 时, 默认槽内容不渲染（品牌由调用方接管）。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import GlassNav from '../GlassNav.vue'
import { useAppStore } from '@/stores/app'

function mountNav(skin: 'cosmic' | 'ios') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAppStore().setSkin(skin)
  return mount(GlassNav, {
    props: {},
    global: { plugins: [pinia] },
  })
}

describe('GlassNav · 默认品牌槽（未传 #brand）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-skin')
    document.documentElement.removeAttribute('data-theme')
  })

  it('cosmic：默认渲染原版图片 logo', () => {
    const wrapper = mountNav('cosmic')
    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350')
  })

  it('ios：同样渲染原版图片 logo（皮肤不改变品牌视觉）', () => {
    const wrapper = mountNav('ios')
    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.find('img').attributes('src')).toContain('NEUROVA-LOGO350')
  })
})
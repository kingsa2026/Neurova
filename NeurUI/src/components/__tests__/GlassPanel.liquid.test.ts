import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

/**
 * GlassPanel 液态玻璃皮肤感知回归测试（2026-09-16 iOS 皮肤重制）。
 *
 * 契约（liquid-glass-web 技能）：
 * 1. cosmic 皮肤（默认）：backdrop 层行为与 09-06 版完全一致——
 *    旧静态位移滤镜 filter:url(#nr-glass-*) 在、backdrop-filter 只有 blur+saturate，
 *    62 个消费方零回归；
 * 2. ios 皮肤：backdrop-filter 前置 url(#glass-liquid-*) 真折射（动态位移图，
 *    官方绝对值参数），旧自身背景 filter 移除避免双重扭曲；
 * 3. 位移图按 radius prop 动态生成（feImage href data:image/svg+xml 含 rx=），
 *    props 变化即重生成；
 * 4. data-skin 切换经 MutationObserver 实时生效；
 * 5. 不支持 backdrop-filter:url() 的浏览器（Safari/Firefox）ios 皮肤降级为
 *    blur+saturate 毛玻璃，不出现 url()；
 * 6. 卸载时 ResizeObserver/MutationObserver 全部 disconnect（防泄漏）。
 */
import GlassPanel from '@/components/GlassPanel.vue'

let roInstances: any[] = []

beforeEach(() => {
  roInstances = []
  class FakeResizeObserver {
    cb: ResizeObserverCallback
    observeSpy = vi.fn()
    disconnectSpy = vi.fn()
    constructor(cb: ResizeObserverCallback) {
      this.cb = cb
      roInstances.push(this)
    }
    observe = this.observeSpy
    disconnect = this.disconnectSpy
    unobserve = vi.fn()
  }
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete (window.navigator as any).userAgent
  document.documentElement.removeAttribute('data-skin')
})

const setSkin = (skin: string) => document.documentElement.setAttribute('data-skin', skin)

describe('GlassPanel 液态玻璃皮肤感知', () => {
  it('cosmic 皮肤零回归：旧静态滤镜在，backdrop-filter 不含 url() 折射', () => {
    setSkin('cosmic')
    const wrapper = mount(GlassPanel, { slots: { default: '<p class="inner">hi</p>' } })
    const backdrop = wrapper.find('.nr-glass-backdrop')
    const style = backdrop.attributes('style') ?? ''
    // jsdom 把 filter 序列化为 -webkit-filter: url("#...")（带引号），正则兼容两种写法
    expect(style).toMatch(/url\(["']?#nr-glass-/) // 旧自身背景滤镜保留
    expect(style).not.toMatch(/url\(["']?#glass-liquid/) // 不启用 backdrop 折射
    wrapper.unmount()
  })

  it('ios 皮肤启用 backdrop 真折射：backdrop-filter 含 url(#glass-liquid-*) 且位移图按 radius 生成', async () => {
    setSkin('ios')
    const wrapper = mount(GlassPanel, { props: { radius: 28 } })
    await nextTick() // 位移图在挂载 nextTick 生成
    const backdrop = wrapper.find('.nr-glass-backdrop')
    const style = backdrop.attributes('style') ?? ''
    expect(style).toMatch(/url\(["']?#glass-liquid-/)
    expect(style).toContain('blur(') // 折射后仍保留磨砂

    const feImage = wrapper.element.querySelector('filter[id^="glass-liquid"] feImage')!
    expect(feImage).toBeTruthy()
    const raw = feImage.getAttribute('href') ?? ''
    expect(raw.startsWith('data:image/svg+xml,')).toBe(true)
    const href = decodeURIComponent(raw.slice('data:image/svg+xml,'.length))
    expect(href).toContain('rx="28"')
    // 官方绝对值参数（禁止比例缩放）：三通道 scale = distortionScale+offset
    const scales = [...wrapper.element.querySelectorAll('filter[id^="glass-liquid"] feDisplacementMap')]
      .map(d => d.getAttribute('scale'))
    expect(scales).toEqual(['-180', '-170', '-160'])
    wrapper.unmount()
  })

  it('data-skin 动态切换实时生效：ios→cosmic 折射撤除', async () => {
    setSkin('ios')
    const wrapper = mount(GlassPanel)
    await nextTick()
    expect(wrapper.find('.nr-glass-backdrop').attributes('style') ?? '').toMatch(/url\(["']?#glass-liquid-/)

    setSkin('cosmic')
    await flushPromises()
    await nextTick()
    expect(wrapper.find('.nr-glass-backdrop').attributes('style') ?? '').not.toMatch(/url\(["']?#glass-liquid-/)
    wrapper.unmount()
  })

  it('ios 皮肤 radius prop 变化触发位移图重生成', async () => {
    setSkin('ios')
    const wrapper = mount(GlassPanel, { props: { radius: 20 } })
    await nextTick()
    const feImage = wrapper.element.querySelector('filter[id^="glass-liquid"] feImage')!
    const readRx = () =>
      decodeURIComponent((feImage.getAttribute('href') ?? '').slice('data:image/svg+xml,'.length)).match(/rx="(\d+)"/)?.[1]
    expect(readRx()).toBe('20')
    await wrapper.setProps({ radius: 36 })
    await nextTick()
    expect(readRx()).toBe('36')
    wrapper.unmount()
  })

  it('不支持 backdrop url() 的浏览器（Firefox UA）ios 皮肤降级为 blur+saturate 无 url()', () => {
    Object.defineProperty(window.navigator, 'userAgent', { value: 'Firefox', configurable: true })
    setSkin('ios')
    const wrapper = mount(GlassPanel)
    const style = wrapper.find('.nr-glass-backdrop').attributes('style') ?? ''
    expect(style).not.toMatch(/url\(["']?#glass-liquid-/)
    expect(style).toContain('blur(')
    wrapper.unmount()
  })

  it('卸载时 ResizeObserver 与 MutationObserver 全部 disconnect', async () => {
    setSkin('ios')
    const moDisconnect = vi.spyOn(MutationObserver.prototype, 'disconnect')
    const wrapper = mount(GlassPanel)
    await nextTick()
    expect(roInstances.length).toBe(1)
    expect(roInstances[0].observeSpy).toHaveBeenCalled()
    wrapper.unmount()
    expect(roInstances[0].disconnectSpy).toHaveBeenCalled()
    expect(moDisconnect).toHaveBeenCalled()
  })
})

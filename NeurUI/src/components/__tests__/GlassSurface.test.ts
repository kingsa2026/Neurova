import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

/**
 * GlassSurface.vue 液态玻璃表面组件回归测试。
 *
 * 移植自 Vue Bits GlassSurface（SVG 位移图驱动的 backdrop-filter 折射玻璃），
 * 针对 Neurova 的适配点即本测试的契约：
 * 1. 主题判定跟随 <html data-theme>（上游用 OS prefers-color-scheme，与应用内主题会劈叉），
 *    且属性切换时经 MutationObserver 实时重算样式；
 * 2. 位移图按容器尺寸 + borderRadius 动态生成并写入 feImage href，props 变化即重生成；
 * 3. ResizeObserver 挂载 observe、卸载 disconnect；MutationObserver 卸载 disconnect（防泄漏）；
 * 4. 无 data-theme 属性且环境无 matchMedia 时安全回退，不抛错。
 */

import GlassSurface from '@/components/GlassSurface.vue'

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
  document.documentElement.removeAttribute('data-theme')
})

/** jsdom 下强制走 supportsSVGFilters=false + 无 backdrop 的降级分支，样式断言才确定 */
const forceFallbackBranch = () => {
  Object.defineProperty(window.navigator, 'userAgent', {
    value: 'Firefox',
    configurable: true,
  })
  if (typeof CSS !== 'undefined') {
    vi.spyOn(CSS, 'supports').mockReturnValue(false)
  }
}

describe('GlassSurface.vue 液态玻璃表面', () => {
  it('渲染容器、SVG 位移滤镜（feImage + 三通道 feDisplacementMap）与插槽内容', () => {
    document.documentElement.setAttribute('data-theme', 'dark')
    const wrapper = mount(GlassSurface, { slots: { default: '<p class="inner">hi</p>' } })
    const el = wrapper.element

    expect(wrapper.find('.nr-glass-surface').exists()).toBe(true)
    expect(el.querySelector('feImage')).toBeTruthy()
    expect(el.querySelectorAll('feDisplacementMap').length).toBe(3)
    expect(el.querySelector('feGaussianBlur')).toBeTruthy()
    expect(wrapper.find('.inner').exists()).toBe(true)
    wrapper.unmount()
  })

  it('位移图按 borderRadius 生成写入 feImage href，props 变化后重生成', async () => {
    document.documentElement.setAttribute('data-theme', 'dark')
    const wrapper = mount(GlassSurface, { props: { borderRadius: 24 } })
    await nextTick() // updateDisplacementMap 在挂载 nextTick 内执行
    const feImage = wrapper.element.querySelector('feImage')!

    const raw = feImage.getAttribute('href') ?? ''
    expect(raw.startsWith('data:image/svg+xml,')).toBe(true)
    let href = decodeURIComponent(raw.slice('data:image/svg+xml,'.length))
    expect(href.trim().startsWith('<svg')).toBe(true)
    expect(href).toContain('rx="24"')

    await wrapper.setProps({ borderRadius: 32 })
    await nextTick()
    href = decodeURIComponent((feImage.getAttribute('href') ?? '').slice('data:image/svg+xml,'.length))
    expect(href).toContain('rx="32"')
    wrapper.unmount()
  })

  it('主题跟随 data-theme 属性：dark/light 底色不同，切换实时重算', async () => {
    forceFallbackBranch()
    document.documentElement.setAttribute('data-theme', 'dark')
    const wrapper = mount(GlassSurface)
    await nextTick() // isDarkMode 在 onMounted 初始化，等重渲染

    // 降级暗色分支底色 rgba(0,0,0,0.4)；亮色分支 rgba(255,255,255,0.4)
    // （box-shadow 简写 jsdom cssstyle 不序列化，断言 background）
    expect(wrapper.attributes('style')).toContain('rgba(0, 0, 0')

    document.documentElement.setAttribute('data-theme', 'light')
    await flushPromises()
    await nextTick()

    expect(wrapper.attributes('style')).toContain('rgba(255, 255, 255, 0.4)')
    wrapper.unmount()
  })

  it('ResizeObserver 挂载即 observe，卸载即 disconnect；MutationObserver 卸载 disconnect', async () => {
    document.documentElement.setAttribute('data-theme', 'dark')
    const moDisconnect = vi.spyOn(MutationObserver.prototype, 'disconnect')

    const wrapper = mount(GlassSurface)
    await nextTick() // setupResizeObserver 在 nextTick 内执行
    expect(roInstances.length).toBe(1)
    expect(roInstances[0].observeSpy).toHaveBeenCalled()

    wrapper.unmount()
    expect(roInstances[0].disconnectSpy).toHaveBeenCalled()
    expect(moDisconnect).toHaveBeenCalled()
  })

  it('无 data-theme 属性且无 matchMedia 时安全回退不抛错', () => {
    expect(() => {
      const wrapper = mount(GlassSurface)
      wrapper.unmount()
    }).not.toThrow()
  })
})

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StarBackground from '@/components/StarBackground.vue'

/**
 * 星空动画回归测试。
 *
 * 背景：b0b86893（Liquid Glass 主题重构）曾把 200 颗星星的 canvas 动画
 * 替换成纯 CSS 静态极光。用户拍板恢复星空、深色主题才显示（v-if 由各
 * 使用页自带），因此组件必须：
 * 1. 渲染 canvas 星空层（.nr-star-canvas）；
 * 2. 保留星云底色层（.nr-nebula）；
 * 3. 挂载即启动 rAF 动画、卸载时取消（防泄漏）；
 * 4. 监听窗口 resize 以同步画布尺寸。
 */
describe('StarBackground.vue 星空动画', () => {
  it('渲染 canvas 星空层与星云底色层', () => {
    const wrapper = mount(StarBackground)
    expect(wrapper.find('.nr-star-bg').exists()).toBe(true)
    expect(wrapper.find('.nr-star-canvas').exists()).toBe(true)
    expect(wrapper.find('.nr-nebula').exists()).toBe(true)
    wrapper.unmount()
  })

  it('挂载启动 rAF 动画，卸载时取消并移除 resize 监听（防泄漏）', () => {
    // jsdom 无真 canvas，stub 2d 上下文让动画路径真正执行
    const fakeCtx = { clearRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn() } as unknown as CanvasRenderingContext2D
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(fakeCtx)

    const rafSpy = vi.spyOn(window, 'requestAnimationFrame')
    const cancelSpy = vi.spyOn(window, 'cancelAnimationFrame')
    let resizeCount = 0
    const originalAdd = window.addEventListener.bind(window)
    vi.spyOn(window, 'addEventListener').mockImplementation((...args: Parameters<typeof window.addEventListener>) => {
      if (args[0] === 'resize') resizeCount++
      return originalAdd(...args)
    })
    const originalRemove = window.removeEventListener.bind(window)
    vi.spyOn(window, 'removeEventListener').mockImplementation((...args: Parameters<typeof window.removeEventListener>) => {
      if (args[0] === 'resize') resizeCount--
      return originalRemove(...args)
    })

    const wrapper = mount(StarBackground)
    expect(rafSpy).toHaveBeenCalled()
    expect(resizeCount).toBe(1)

    wrapper.unmount()
    expect(cancelSpy).toHaveBeenCalled()
    expect(resizeCount).toBe(0)

    vi.restoreAllMocks()
  })

  it('jsdom 无 2d 上下文时安全跳过初始化（不抛错）', () => {
    expect(() => {
      const wrapper = mount(StarBackground)
      wrapper.unmount()
    }).not.toThrow()
  })
})

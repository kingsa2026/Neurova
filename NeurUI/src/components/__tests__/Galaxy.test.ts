import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'

/**
 * Galaxy.vue 银河背景组件回归测试。
 *
 * 移植自 Vue Bits Galaxy（ogl WebGL 全屏星流 shader），针对 Neurova 的适配点：
 * 1. 作为页面背景层：容器铺满父级 + pointer-events:none，因此鼠标交互
 *    监听挂在 window 而非容器上（原组件挂容器，背景层收不到事件）；
 * 2. 归一化用视口尺寸（jsdom/零宽容器下 getBoundingClientRect 除零安全）；
 * 3. 卸载必须清理：rAF、window resize、window mousemove、document mouseleave、
 *    canvas 摘除、WEBGL_lose_context——防 WebGL 上下文与监听器泄漏；
 * 4. disableAnimation=true 时冻结 uTime/uStarSpeed（reduced-motion 门控用）。
 *
 * jsdom 无 WebGL，故 vi.mock('ogl') 以捕获实例断言 uniform 行为。
 */

const oglState = vi.hoisted(() => {
  const programs: any[] = []
  const renderers: any[] = []
  const loseContext = vi.fn()
  return { programs, renderers, loseContext }
})

vi.mock('ogl', () => {
  class Renderer {
    gl: any
    setSize = vi.fn()
    render = vi.fn()
    constructor(opts: any = {}) {
      const canvas = document.createElement('canvas')
      this.gl = {
        canvas,
        enable: vi.fn(),
        blendFunc: vi.fn(),
        clearColor: vi.fn(),
        getExtension: vi.fn(() => ({ loseContext: oglState.loseContext })),
      }
      oglState.renderers.push(this)
    }
  }
  class Program {
    uniforms: any
    constructor(_gl: any, opts: any) {
      this.uniforms = opts.uniforms
      oglState.programs.push(this)
    }
  }
  class Mesh {}
  class Triangle {}
  class Color {
    r: number; g: number; b: number
    constructor(r: number, g: number, b: number) { this.r = r; this.g = g; this.b = b }
  }
  return { Renderer, Program, Mesh, Triangle, Color }
})

import Galaxy from '@/components/Galaxy.vue'

/** 手动驱动 rAF 帧：id 登记表模拟 cancel 语义，避免 jsdom 下动画回调无限自续 */
let pendingRaf = new Map<number, FrameRequestCallback>()
let rafNextId = 1
let cancelSpy: ReturnType<typeof vi.spyOn>
const tick = (t: number) => {
  const cbs = [...pendingRaf.values()]
  pendingRaf.clear()
  cbs.forEach((cb) => cb(t))
}

beforeEach(() => {
  oglState.programs.length = 0
  oglState.renderers.length = 0
  oglState.loseContext.mockClear()
  pendingRaf = new Map()
  rafNextId = 1
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    const id = rafNextId++
    pendingRaf.set(id, cb)
    return id
  })
  cancelSpy = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    pendingRaf.delete(id as number)
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Galaxy.vue 银河背景', () => {
  it('渲染背景容器并把 WebGL canvas 挂载到容器内', () => {
    const wrapper = mount(Galaxy)
    expect(wrapper.find('.nr-galaxy').exists()).toBe(true)
    const canvas = oglState.renderers[0].gl.canvas
    expect(wrapper.element.contains(canvas)).toBe(true)
    wrapper.unmount()
  })

  it('挂载即初始化透明 renderer 与全部 uniform', () => {
    const wrapper = mount(Galaxy)
    const program = oglState.programs[0]
    expect(program.uniforms.uTransparent.value).toBe(true)
    expect(program.uniforms.uHueShift.value).toBe(140)
    expect(program.uniforms.uMouseActiveFactor.value).toBe(0)
    wrapper.unmount()
  })

  it('window mousemove 驱动鼠标交互 uniform（背景层 pointer-events:none 下仍可交互）', () => {
    const wrapper = mount(Galaxy)
    const program = oglState.programs[0]

    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 256, clientY: 512 }))
    tick(1000)

    // jsdom 视口 1024×768：x=0.25, y=1-0.667=0.333；lerp 每帧 0.05 → 未到位但应离开 0.5
    expect(program.uniforms.uMouse.value[0]).toBeLessThan(0.5)
    expect(program.uniforms.uMouseActiveFactor.value).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('document mouseleave 后交互因子回落', () => {
    const wrapper = mount(Galaxy)
    const program = oglState.programs[0]

    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 500, clientY: 300 }))
    for (let i = 0; i < 60; i++) tick(1000 + i)
    const activePeak = program.uniforms.uMouseActiveFactor.value
    expect(activePeak).toBeGreaterThan(0.9)

    document.dispatchEvent(new MouseEvent('mouseleave'))
    for (let i = 0; i < 60; i++) tick(2000 + i)
    expect(program.uniforms.uMouseActiveFactor.value).toBeLessThan(0.1)
    wrapper.unmount()
  })

  it('disableAnimation=true 时冻结时间 uniform', () => {
    const wrapper = mount(Galaxy, { props: { disableAnimation: true } })
    const program = oglState.programs[0]
    tick(5000)
    expect(program.uniforms.uTime.value).toBe(0)
    wrapper.unmount()
  })

  it('mouseInteraction=false 时不注册 window mousemove 监听', () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const wrapper = mount(Galaxy, { props: { mouseInteraction: false } })
    expect(addSpy.mock.calls.some((c) => c[0] === 'mousemove')).toBe(false)
    wrapper.unmount()
  })

  it('卸载完整清理：rAF/监听器/canvas/WebGL 上下文', () => {
    const wrapper = mount(Galaxy)
    const canvas = oglState.renderers[0].gl.canvas
    const renderer = oglState.renderers[0]
    tick(1000) // 推进一帧，让 render 计数离开 0
    const renderCalls = renderer.render.mock.calls.length

    wrapper.unmount()

    expect(cancelSpy).toHaveBeenCalled()
    expect(renderer.gl.getExtension).toHaveBeenCalledWith('WEBGL_lose_context')
    expect(oglState.loseContext).toHaveBeenCalled()
    expect(wrapper.element.contains(canvas)).toBe(false)

    // 卸载后派发事件/帧不再触发渲染（监听器与 rAF 链均已摘除）
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 100, clientY: 100 }))
    tick(9999)
    expect(renderer.render.mock.calls.length).toBe(renderCalls)
  })
})

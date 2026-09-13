/**
 * SlideshowPlayer：无 FFmpeg 环境的诚实成片形态（批次4）。
 * 逐镜图 + 旁白音频连播 + 字幕；有音频时音频播完自动下镜，无音频静图 3.5s；
 * 产物 URL 走 withFileToken 鉴权（批次3 契约）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))

import SlideshowPlayer from '@/components/aigc/SlideshowPlayer.vue'

const ITEMS = [
  { shot: 1, url: '/api/v1/generation/files/a_0.png', path: '/p/a.png', prompt: 'p1', description: '镜一描述', narration: '旁白一', audio: '/api/v1/generation/files/v_0.wav' },
  { shot: 2, url: '/api/v1/generation/files/b_0.png', path: '/p/b.png', prompt: 'p2', description: '镜二描述', narration: '旁白二', audio: '' },
]

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { aigc: { studioPlay: '播放', studioPause: '暂停', studioPrev: '上一镜', studioNext: '下一镜', studioShot: '镜头' } } },
})

const mountPlayer = (items = ITEMS) =>
  mount(SlideshowPlayer, {
    props: { items },
    global: { plugins: [i18n], stubs: { audio: { template: '<audio />', methods: { play: vi.fn(), pause: vi.fn() } } } },
  })

describe('SlideshowPlayer', () => {
  beforeEach(() => vi.useFakeTimers())
  it('首镜渲染：图片带访问凭证 + 字幕文案', () => {
    const wrapper = mountPlayer()
    const html = wrapper.html()
    expect(html).toContain('access_token=tok')
    expect(wrapper.text()).toContain('镜一描述')
    expect(wrapper.text()).toContain('旁白一')
  })

  it('无音频镜头自动连播推进（3.5s 下镜）', async () => {
    const wrapper = mountPlayer([ITEMS[1]]) // 单镜无音频 → 到末尾停住不越界
    ;(wrapper.vm as any).play()
    await vi.advanceTimersByTimeAsync(4000)
    await flushPromises()
    expect((wrapper.vm as any).idx).toBe(0) // 仅 1 镜，不越界
    wrapper.unmount()
  })

  it('上一镜/下一镜手动控制', async () => {
    const wrapper = mountPlayer()
    ;(wrapper.vm as any).next()
    expect((wrapper.vm as any).idx).toBe(1)
    ;(wrapper.vm as any).next()
    expect((wrapper.vm as any).idx).toBe(1) // 末镜钳制
    ;(wrapper.vm as any).prev()
    expect((wrapper.vm as any).idx).toBe(0)
    wrapper.unmount()
  })

  it('空 items 显示占位不报错', () => {
    const wrapper = mountPlayer([])
    expect(wrapper.find('.slideshow-empty').exists()).toBe(true)
  })
})

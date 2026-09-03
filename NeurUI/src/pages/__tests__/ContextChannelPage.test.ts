/**
 * ContextChannelPage（渠道共享）— 契约对齐防回归测试（2026-09-03）
 *
 * 场景（实测根因）：页面按「数组」解析 GET /channel-sharing，而后端该端点
 * 返回配置信封 {code, data:{config:{...}}}；v-for 遍历信封对象 → 每张卡片
 * channelName undefined → 卡片标题全空。
 *
 * 契约（防回归）：
 * 1. 列表数据源 = GET /channel-sharing/available-channels 的
 *    data.channels[{type,label,is_shared}]，卡片标题显示 label
 * 2. 测试连接 = POST /channel-sharing/test 携带 {channel: type}（不再是 {channelId}）
 * 3. 开关 = POST /channel-sharing/channels 携带 {channels, shared_context}
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

import { mount as _m } from '@vue/test-utils'
import { request } from '@/api'
import ContextChannelPage from '@/pages/ContextChannelPage.vue'

const requestMock = request as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { back: '返回', active: '已激活', inactive: '未激活', noData: '暂无数据' },
      channel: { sharing: '渠道共享', config: '渠道配置', test: '测试连接', session: '会话' },
    },
  },
})

const envelopeChannels = {
  code: 0,
  data: {
    channels: [
      { type: 'web', label: 'Web 前端', description: 'Web 渠道', is_shared: true },
      { type: 'mobile', label: '移动端', description: '移动渠道', is_shared: false },
    ],
    total: 2,
    shared_count: 1,
  },
}

const mountPage = () =>
  _m(ContextChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-badge': { props: ['text'], template: '<span class="stub-badge">{{ text }}</span>' },
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-switch': {
          props: ['checked'],
          emits: ['change'],
          template: '<span class="stub-switch" @click="$emit(\'change\', !checked)" />',
        },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-spin': { template: '<div><slot /></div>' },
      },
    },
  })

describe('ContextChannelPage 契约对齐（渠道共享列表）', () => {
  beforeEach(() => {
    requestMock.get.mockReset()
    requestMock.post.mockReset()
    requestMock.get.mockImplementation((url: string) => {
      if (url === '/channel-sharing/available-channels') return Promise.resolve(envelopeChannels)
      return Promise.resolve({ code: 0, data: { config: { enabled: true, shared_channels: ['web'] } } })
    })
  })

  it('从 available-channels 的 data.channels 渲染渠道名称（信封契约）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(requestMock.get).toHaveBeenCalledWith('/channel-sharing/available-channels')
    const text = wrapper.text()
    expect(text).toContain('Web 前端')
    expect(text).toContain('移动端')
    expect(text).toContain('已激活')
    expect(text).toContain('未激活')
  })

  it('测试连接使用 {channel: type} 契约', async () => {
    requestMock.post.mockResolvedValue({ code: 0 })
    const wrapper = mountPage()
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const testBtn = buttons.find((b) => b.text().includes('测试连接'))
    expect(testBtn).toBeTruthy()
    await testBtn!.trigger('click')
    await flushPromises()
    expect(requestMock.post).toHaveBeenCalledWith('/channel-sharing/test', { channel: 'web' })
  })

  it('开关通过 /channels 更新共享渠道集合', async () => {
    requestMock.post.mockResolvedValue({ code: 0 })
    const wrapper = mountPage()
    await flushPromises()
    const switches = wrapper.findAll('.stub-switch')
    expect(switches.length).toBe(2)
    await switches[1].trigger('click')
    await flushPromises()
    expect(requestMock.post).toHaveBeenCalledWith('/channel-sharing/channels', {
      channels: ['web', 'mobile'],
      shared_context: true,
    })
  })
})

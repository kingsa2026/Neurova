/**
 * AgentPersonalityPage — 多语言适配 TDD 测试
 *
 * 契约:
 *   /agent/:agentId/personality 页面的所有可见文案必须走 i18n (t()):
 *   1. 6 个特质名 (开放性/尽责性/...) 必须来自 personality.* key,
 *      不能硬编码英文 "Openness" 等 (否则 en-US 以外的语言显示英文).
 *   2. 页面标题/按钮 (emotion.personality, growth.evolve, common.*)
 *      随 locale 切换.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import AgentPersonalityPage from '@/pages/AgentPersonalityPage.vue'

// Mock the axios wrapper — mount-time fetch must not hit network
vi.mock('@/api', () => ({
  request: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// Mock ant-design-vue message to avoid DOM side effects
vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import { request } from '@/api'

const zhMessages = {
  common: { refresh: '刷新', edit: '编辑', cancel: '取消', save: '保存', success: '操作成功', error: '操作失败' },
  emotion: { personality: '个性管理' },
  growth: { evolve: '进化', personality: '个性档案', traits: '特质' },
  personality: {
    title: '人格特征',
    openness: '开放性',
    conscientiousness: '尽责性',
    extraversion: '外向性',
    agreeableness: '宜人性',
    neuroticism: '神经质',
    creativity: '创造力',
  },
}

const enMessages = {
  common: { refresh: 'Refresh', edit: 'Edit', cancel: 'Cancel', save: 'Save', success: 'Success', error: 'Error' },
  emotion: { personality: 'Personality Management' },
  growth: { evolve: 'Evolve', personality: 'Personality Profile', traits: 'Traits' },
  personality: {
    title: 'Personality',
    openness: 'Openness',
    conscientiousness: 'Conscientiousness',
    extraversion: 'Extraversion',
    agreeableness: 'Agreeableness',
    neuroticism: 'Neuroticism',
    creativity: 'Creativity',
  },
}

const globalStubs = {
  GlassCard: { template: '<div><slot name="title"/><slot/><slot name="footer"/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button @click="$emit(\'click\')"><slot/></button>',
  },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-slider': { props: ['value'], template: '<div class="slider-stub"/>' },
}

function mountPage(locale: string, messages: Record<string, any>) {
  const i18n = createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'zh-CN',
    messages: { [locale]: messages, 'zh-CN': zhMessages },
    globalInjection: true,
  })
  return mount(AgentPersonalityPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

describe('AgentPersonalityPage — 多语言适配', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(request.get).mockResolvedValue({ data: {} } as any)
  })

  it('zh-CN 下 trait 名显示中文翻译而非硬编码英文', async () => {
    const wrapper = mountPage('zh-CN', zhMessages)
    await flushPromises()

    const names = wrapper.findAll('.trait-name').map((n) => n.text())
    expect(names.join(',')).toBe('开放性,尽责性,外向性,宜人性,神经质,创造力')
    expect(names.join(','), '必须翻译, 不能是 Openness 等英文').not.toContain('Openness')
  })

  it('en-US 下 trait 名显示英文', async () => {
    const wrapper = mountPage('en-US', enMessages)
    await flushPromises()

    const names = wrapper.findAll('.trait-name').map((n) => n.text())
    expect(names.join(',')).toBe('Openness,Conscientiousness,Extraversion,Agreeableness,Neuroticism,Creativity')
  })

  it('页面标题与按钮随 locale 切换', async () => {
    const wrapper = mountPage('zh-CN', zhMessages)
    await flushPromises()

    expect(wrapper.find('.page-title').text()).toBe('个性管理')
    const buttons = wrapper.findAll('button').map((b) => b.text())
    expect(buttons.join(',')).toContain('进化')
    expect(buttons.join(',')).toContain('刷新')
  })
})

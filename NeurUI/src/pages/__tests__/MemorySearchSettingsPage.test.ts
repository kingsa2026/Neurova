/**
 * MemorySearchSettingsPage — 首帧渲染拆分 TDD 测试
 *
 * 根因: DevTools [Violation] 'setTimeout' handler took 59ms
 *   runtime-dom.esm-bundler.js:311 = Vue Transition(whenTransitionEnds) 兜底定时器。
 *   页面挂载即渲染完整表单(默认值) + a-spin 遮罩过渡; 随后 3 个并行请求返回,
 *   全页状态更新触发第二轮 patch, 该帧同时包含 antd detectFlexGapSupported 首调
 *   (document.body.appendChild + scrollHeight 强制整页样式/布局) — 慢机器/DevTools 下
 *   同步工作 >50ms, 被 DevTools 归因给同帧最近的 setTimeout handler。
 *
 * 契约 (防回归):
 *   1. 初始请求未返回前, 页面「不渲染」表单卡片, 只渲染轻量占位
 *      (取消「默认值表单 → 真值表单」两轮 patch, 首帧 DOM 保持轻)。
 *   2. 数据返回后一次性渲染完整表单, 且展示真值而非默认值。
 *   3. 刷新按钮行为不变(仍可重新拉取)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import MemorySearchSettingsPage from '@/pages/MemorySearchSettingsPage.vue'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
}))

vi.mock('@/api/modules/memory', () => ({
  getNerfSettings: vi.fn(),
  updateNerfSettings: vi.fn(),
  resetNerfSettings: vi.fn(),
  getChannelWeights: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
}))

// 页面为全局设置, 仅管理员可操作 —— mock 认证为 admin (2026-08-31)
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { id: 'u-admin', username: 'adminuser', role: 'admin' },
  }),
}))

import { request } from '@/api'
import { getNerfSettings, getChannelWeights } from '@/api/modules/memory'
import type { ApiResponse } from '@/types/response'
import type { NerfSettings, ChannelWeights } from '@/api/modules/memory'

const messages = {
  common: {
    refresh: '刷新', save: '保存', reset: '重置', success: '操作成功', error: '操作失败', noData: '暂无数据', loading: '加载中...',
    globalSettingHint: '本页面为全局系统配置/数据，对所有用户生效',
    adminOnlyHint: '仅管理员可访问与操作，当前账号无权限',
  },
  memory: { decay: '记忆衰减', enhance: '记忆增强' },
  memorySearch: {
    title: '记忆搜索设置',
    searchMethod: '搜索方式',
    hybrid: '混合',
    bm25: 'BM25',
    vector: '向量',
    topK: 'Top K 结果',
    scoreThreshold: '分数阈值',
    enableDecay: '启用衰减',
    decayRate: '衰减率',
    halfLife: '半衰期 (天)',
    minScoreFloor: '最低分数',
    enableEnhancement: '启用增强',
    boostFactor: '增强因子',
    recencyWeight: '时间权重',
    frequencyWeight: '频率权重',
    testSearch: '测试搜索',
    testQueryPlaceholder: '输入测试查询...',
    nerfTitle: 'NeRF 体渲染融合',
    nerfMode: '融合模式',
    nerfLegacy: 'Legacy',
    nerfLegacyDesc: '传统加权求和',
    nerfNerf: 'NeRF',
    nerfNerfDesc: 'NeRF 体渲染',
    densityScale: '密度缩放因子',
    densityScaleHint: '控制通道间遮挡强度',
    channelDensities: '通道密度（置信度）',
    intentWeightPreview: '意图通道权重预览',
    intentFactual: 'Factual (事实)',
    intentTemporal: 'Temporal (时间)',
    intentCausal: 'Causal (因果)',
    intentComparative: 'Comparative (比较)',
    intentExploratory: 'Exploratory (探索)',
    channelText: '文本',
    channelTemperature: '温度',
    channelCategory: '分类',
    channelGraph: '图谱',
    channelEmotion: '情感',
    channelVoice: '语音',
    nerfTag: 'NeRF 专用标签',
    saved: 'NeRF 设置已保存',
    resetDone: 'NeRF 设置已重置',
  },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div><h3>{{ title }}</h3><slot/><slot name="footer"/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button @click="$emit(\'click\')"><slot/></button>',
  },
  'a-spin': { props: ['spinning'], template: '<div class="ant-spin"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': {
    props: ['label', 'extra'],
    template: '<div class="ant-form-item"><label>{{ label }}</label><slot/></div>',
  },
  'a-radio-group': { props: ['value'], emits: ['update:value'], template: '<div class="ant-radio-group" :data-value="value"><slot/></div>' },
  'a-radio-button': { props: ['value'], template: '<button type="button"><slot/></button>' },
  'a-input-number': { props: ['value'], emits: ['update:value'], template: '<input class="ant-input-number" :value="value" />' },
  'a-slider': { props: ['value', 'min', 'max', 'step'], emits: ['update:value'], template: '<input type="range" class="ant-slider" :value="value" />' },
  'a-switch': {
    props: ['checked'],
    emits: ['update:checked'],
    template: '<button class="ant-switch"><slot/></button>',
  },
  'a-tooltip': { template: '<span><slot/></span>' },
  'a-select': { props: ['value'], emits: ['update:value'], template: '<div><select/><slot/></div>' },
  'a-select-option': { props: ['value'], template: '<option :value="value"><slot/></option>' },
  'a-list': {
    props: ['dataSource'],
    template: '<div class="ant-list"><slot name="renderItem" v-for="(item, i) in dataSource" :key="i" :item="item"/></div>',
  },
  'a-list-item': { template: '<div class="ant-list-item"><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}<slot/></div>' },
  'a-input-search': {
    props: ['value', 'placeholder'],
    emits: ['update:value', 'search'],
    template: '<input class="ant-input-search" :placeholder="placeholder" :value="value" @input="$emit(\'update:value\', $event.target.value)" @keyup.enter="$emit(\'search\', value)" />',
  },
}

const settingsPayload = {
  data: {
    search: { method: 'vector', top_k: 42, score_threshold: 50 },
    decay: { enabled: false, rate: 10, half_life_days: 99, min_score: 5 },
    enhancement: { enabled: true, boost_factor: 3, recency_weight: 20, frequency_weight: 80 },
  },
}

const nerfPayload: ApiResponse<NerfSettings> = {
  code: 0,
  message: 'ok',
  data: {
    fusion_mode: 'nerf',
    density_scale: 2.0,
    channel_densities: { text: 0.1, temperature: 0.2, category: 0.3, graph: 0.4, emotion: 0.5, voice: 0.6 },
    available_modes: ['legacy', 'nerf'],
    mode_descriptions: { legacy: '传统加权求和', nerf: 'NeRF 体渲染' },
  },
}

const weightsPayload: ApiResponse<ChannelWeights> = {
  code: 0,
  message: 'ok',
  data: { intent: 'exploratory', weights: { text: 0.9, category: 0.4 } },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(MemorySearchSettingsPage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(request.get).mockResolvedValue({ ...settingsPayload })
  vi.mocked(request.put).mockResolvedValue({ code: 0 })
  vi.mocked(request.post).mockResolvedValue({ data: { results: [] } })
  vi.mocked(getNerfSettings).mockResolvedValue({ ...nerfPayload })
  vi.mocked(getChannelWeights).mockResolvedValue({ ...weightsPayload })
})

describe('MemorySearchSettingsPage 首帧渲染', () => {
  it('请求未返回时只渲染占位，不渲染表单卡片（避免默认值→真值两轮全页 patch）', () => {
    const wrapper = mountPage()

    // 表单内容(搜索方式/save 按钮等)在请求完成前不可见
    expect(wrapper.text()).not.toContain('搜索方式')
    expect(wrapper.text()).not.toContain('混合')
    // 占位可见(加载中)
    expect(wrapper.text()).toContain('加载中...')
    // 卡片主体未渲染: 卡片标题不应重复出现
    expect(wrapper.text()).not.toContain('记忆衰减')
  })

  it('数据返回后一次性渲染完整表单并回填真值', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('记忆搜索设置')
    expect(wrapper.text()).toContain('搜索方式')
    expect(wrapper.text()).toContain('混合') // hybrid radio
    expect(wrapper.text()).toContain('BM25')
    expect(wrapper.text()).toContain('向量')
    expect(wrapper.text()).toContain('记忆衰减')
    expect(wrapper.text()).toContain('记忆增强')
    expect(wrapper.text()).toContain('NeRF 体渲染融合')
    // 数据回填: 方法为 vector(后端真值), 而非默认 hybrid
    expect(wrapper.find('.ant-radio-group').attributes('data-value')).toBe('vector')
    // TopK 42 为后端真值(默认 10)
    expect(wrapper.find('input.ant-input-number').attributes('value')).toBe('42')
    // 权重条渲染(意图通道权重预览)
    expect(wrapper.text()).toContain('文本')
    expect(wrapper.findAll('.weight-bar-row').length).toBeGreaterThan(0)
  })

  it('请求失败时仍显示表单(实测默认配置)，不永久留白', async () => {
    vi.mocked(request.get).mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('搜索方式')
    expect(wrapper.text()).toContain('混合')
  })

  it('测试结果 NeRF 标签走 nerfTag i18n 键（非硬编码）', async () => {
    vi.mocked(request.post).mockResolvedValue({
      data: { results: [{ content: '结果A', score: 0.9, channel_scores: { text: 0.8 } }] },
    })
    const wrapper = mountPage()
    await flushPromises()

    const input = wrapper.find('input.ant-input-search')
    await input.setValue('测试查询')
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(wrapper.text()).toContain('NeRF 专用标签')
  })
})

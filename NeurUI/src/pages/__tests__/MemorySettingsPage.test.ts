/**
 * MemorySettingsPage — 多语言适配契约测试（红绿灯 TDD）
 *
 * 根因（2026-09-02 审计）:
 *   1. 保存条 "N 参数 changed" — "changed" 英文硬编码, 中文界面混英文。
 *   2. 参数类型标签直接显示原始 float/int/bool（zh-CN 界面同样是英文）。
 *   3. 参数描述直接透出后端中文 description（settings_config.py PARAM_SCHEMAS）,
 *      非中文语言界面每条说明都是中文 — 前端未走 desc_key/i18n。
 *
 * 契约（防回归）:
 *   1. 保存条渲染 memorySettings.changedHint 插值结果, 不得出现硬编码 "changed"。
 *   2. 类型标签走 typeFloat/typeInt/typeBool/typeString 键。
 *   3. 存在 desc_key 且当前语言有对应键时, 描述用 t(desc_key);
 *      无 desc_key（或键缺失）时回退 param.description。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import MemorySettingsPage from '@/pages/MemorySettingsPage.vue'

vi.mock('@/api/modules/memory-settings', () => ({
  getSchema: vi.fn(),
  updateSettings: vi.fn(),
  resetSettings: vi.fn(),
  exportSettings: vi.fn(),
  importSettings: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { id: 'u-admin', username: 'adminuser', role: 'admin' },
  }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import { getSchema } from '@/api/modules/memory-settings'
import type { ParamSchema } from '@/api/modules/memory-settings'

const messages = {
  common: {
    refresh: '刷新', save: '保存', reset: '重置', cancel: '取消', error: '操作失败',
  },
  memorySettings: {
    title: '记忆系统配置',
    subtitle: '调整记忆系统各子模块的运行参数',
    globalHint: '本页面为全局设置，修改将影响所有用户与智能体',
    adminOnlyHint: '仅管理员可修改全局记忆系统参数，当前为只读查看',
    allSettings: '全部参数',
    reset: '重置',
    resetAll: '重置全部',
    resetSelected: '重置选中项',
    export: '导出配置',
    import: '导入配置',
    save: '保存更改',
    defaultValue: '默认值',
    modified: '已修改',
    noSchema: '无法获取参数 Schema',
    paramKey: '参数',
    changedHint: '{n} 个参数已修改',
    typeFloat: '浮点数',
    typeInt: '整数',
    typeBool: '布尔值',
    typeString: '字符串',
    paramNameTemperatureDecayRate: '温度衰减速率',
    paramNameGraphBeamWidth: '搜索宽度',
    paramtemperatureDecayRate: '温度衰减率（每小时）',
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
  'a-dropdown': { template: '<div class="ant-dropdown"><slot/><slot name="overlay"/></div>' },
  'a-menu': { template: '<div class="ant-menu"><slot/></div>' },
  'a-menu-item': { emits: ['click'], template: '<div class="ant-menu-item"><slot/></div>' },
  'a-upload': { props: ['accept'], template: '<span class="ant-upload"><slot/></span>' },
  'a-checkbox': { props: ['checked'], emits: ['change'], template: '<input type="checkbox" class="ant-checkbox" :checked="checked" />' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-switch': { props: ['checked'], emits: ['update:checked'], template: '<button class="ant-switch"><slot/></button>' },
  'a-slider': { props: ['value'], emits: ['update:value'], template: '<input type="range" class="ant-slider" :value="value" />' },
  'a-input-number': {
    props: ['value'],
    emits: ['update:value'],
    template: '<input class="ant-input-number" :value="value" @input="$emit(\'update:value\', parseFloat($event.target.value))" />',
  },
  'a-input': { props: ['value'], emits: ['update:value'], template: '<input class="ant-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}<slot/></div>' },
}

// api.get 类型为 Promise<T>，getSchema 直接返回 ParamSchema[]（无信封）
const schemaPayload: ParamSchema[] = [
  {
    key: 'temperature.decay_rate', default: 0.1, type: 'float', min: 0, max: 1,
    description: '记忆温度衰减速率（每小时）',
    desc_key: 'memorySettings.paramtemperatureDecayRate',
    current: 0.1,
  },
  {
    key: 'graph.beam_width', default: 3, type: 'int', min: 1, max: 20,
    description: 'beam search 宽度',
    current: 3,
  },
  {
    key: 'compression.enable_llm_compression', default: true, type: 'bool', min: null, max: null,
    description: '是否启用 LLM 辅助压缩',
    current: true,
  },
]

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(MemorySettingsPage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getSchema).mockResolvedValue([...schemaPayload])
})

describe('MemorySettingsPage 多语言适配', () => {
  it('保存条显示本地化变更提示（无硬编码 changed）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // float 参数输入 0.5 → 1 个参数变更 → 保存条出现
    const input = wrapper.find('input.ant-input-number')
    await input.setValue('0.5')

    expect(wrapper.text()).toContain('1 个参数已修改')
    expect(wrapper.text()).not.toContain('changed')
    expect(wrapper.text()).not.toContain('参数 changed')
  })

  it('参数类型标签显示本地化名称而非原始 float/int/bool', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('浮点数')
    expect(wrapper.text()).toContain('整数')
    expect(wrapper.text()).toContain('布尔值')
    expect(wrapper.text()).not.toContain('float')
    expect(wrapper.text()).not.toContain('int ')
    expect(wrapper.text()).not.toContain('bool')
  })

  it('描述优先走 desc_key 的 i18n 渲染，缺失时回退 description', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // 有 desc_key → 渲染语言包值（与后端 description 不同，可区分）
    expect(wrapper.text()).toContain('温度衰减率（每小时）')
    expect(wrapper.text()).not.toContain('记忆温度衰减速率（每小时）')
    // 无 desc_key → 回退 description
    expect(wrapper.text()).toContain('beam search 宽度')
  })

  it('参数名走 paramName<Key> i18n 映射，未登记键回落剥离前缀的原始名', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // 已登记 → 语言包名称（不再显示 snake_case 键名）
    expect(wrapper.text()).toContain('温度衰减速率')
    expect(wrapper.text()).not.toContain('decay_rate')
    // 未登记 → 回落剥离前缀（compression.enable_llm_compression → enable_llm_compression）
    expect(wrapper.text()).toContain('enable_llm_compression')
    // 原始键保留在 title tooltip
    expect(wrapper.html()).toContain('title="temperature.decay_rate"')
  })
})

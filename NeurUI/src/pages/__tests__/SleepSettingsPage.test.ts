/**
 * SleepSettingsPage — 自动睡眠联动显隐 TDD 测试
 *
 * 契约 (自动睡眠参数分级):
 *   开启 auto_sleep_enabled 后, 对自动路径无效的参数必须隐藏:
 *     - sleep_duration_minutes (仅手动入睡的缺省时长)
 *     - dream_replay_enabled (梦境日志仅手动入睡产生)
 *   关闭 auto_sleep_enabled 后, 全部参数可见 (含手动参数, 供开启前配置)。
 *   隐藏的项仍参与保存 (payload 不变, 只是不可见)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SleepSettingsPage from '@/pages/SleepSettingsPage.vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' } }),
}))

vi.mock('@/api/modules/sleep', async (importOriginal) => {
  const actual = await importOriginal<any>()
  return {
    ...actual,
    getSleepSettings: vi.fn(),
    updateSleepSettings: vi.fn().mockResolvedValue({}),
    getMergeConflicts: vi.fn().mockResolvedValue([]),
    resolveConflict: vi.fn().mockResolvedValue({}),
  }
})

vi.mock('ant-design-vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('ant-design-vue')>()
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})

import { getSleepSettings } from '@/api/modules/sleep'
import type { ApiResponse } from '@/types/response'
import type { SleepSettings } from '@/api/modules/sleep'

const messages = {
  common: {
    refresh: '刷新', save: '保存', reset: '重置', success: '操作成功', error: '操作失败', noData: '暂无数据',
  },
  sleep: {
    settings: '睡眠设置',
    enableAutoSleep: '启用自动休眠',
    sleepThresholdMinutes: '休眠触发阈值 (分钟)',
    sleepDurationMinutes: '休眠时长 (分钟)',
    enableDreaming: '启用梦境',
    enableMemoryMerge: '启用记忆合并',
    enableConflictResolution: '启用冲突解决',
    minutes: '分钟',
    conflicts: '冲突解决',
    resolved: '已解决', pending: '待处理',
    localValue: '本地值', remoteValue: '远程值',
    keepLocal: '保留本地', keepRemote: '保留远程', customResolve: '自定义解决',
    conflictField: '冲突字段', resolutionValue: '解决内容', resolutionPlaceholder: '输入解决方案',
    minIntervalValidation: '取值超出范围',
    manualOnlyHint: '仅手动"进入睡眠"时生效，自动休眠不使用',
    phaseParams: '睡眠节奏（阶段推进）',
    sleepMode: '判定模式',
    modeTemperature: '按记忆温度',
    modeTime: '按空闲时长',
    modeEither: '温度或空闲任一满足',
    threshold: '阈值',
    monitorIntervalSeconds: '阶段监控间隔',
    seconds: '秒',
    hibernatePhase: '休眠阶段',
    lightPhase: '浅睡眠阶段',
    deepPhase: '深睡眠阶段',
    remPhase: 'REM 阶段',
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
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': {
    props: ['label', 'extra'],
    template:
      '<div class="ant-form-item"><label class="ant-form-item-label">{{ label }}</label><slot/><div v-if="extra" class="ant-form-item-extra">{{ extra }}</div></div>',
  },
  'a-switch': {
    props: ['checked'],
    emits: ['update:checked'],
    template:
      '<button class="ant-switch" :class="{ \'ant-switch-checked\': checked }" @click="$emit(\'update:checked\', !checked)"></button>',
  },
  'a-input-number': {
    props: ['value', 'addonAfter'],
    emits: ['update:value'],
    template:
      '<span class="ant-input-number-wrapper"><input class="ant-input-number"/><span v-if="addonAfter" class="ant-input-number-group-addon">{{ addonAfter }}</span></span>',
  },
  'a-row': { template: '<div><slot/></div>' },
  'a-col': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-empty': { template: '<div/>' },
  'a-space': { template: '<div><slot/></div>' },
  'a-modal': { props: ['open'], template: '<div v-if="open"><slot/></div>' },
  'a-textarea': { props: ['value'], emits: ['update:value'], template: '<textarea/>' },
  'a-select': { props: ['value'], emits: ['update:value'], template: '<select class="ant-select" @change="$emit(\'update:value\', $event.target.value)"><slot/></select>' },
  'a-select-option': { props: ['value'], template: '<option :value="value"><slot/></option>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(SleepSettingsPage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

function visibleLabels(wrapper: any): string[] {
  return wrapper
    .findAll('.ant-form-item')
    .map((el: any) => el.find('.ant-form-item-label').text())
    .filter(Boolean)
}

const MANUAL_ONLY = ['休眠时长 (分钟)', '启用梦境']
const AUTO_RELEVANT = ['休眠触发阈值 (分钟)', '启用记忆合并', '启用冲突解决']

const sleepSettingsResponse: ApiResponse<SleepSettings> = {
  code: 0,
  message: 'ok',
  data: {
    agent_id: 'default',
    auto_sleep_enabled: true,
    sleep_threshold_minutes: 30,
    sleep_duration_minutes: 60,
    dream_replay_enabled: true,
    memory_consolidation_enabled: true,
    conflict_resolution_enabled: true,
    sleep_mode: 'temperature',
    temp_threshold_light_sleep: 30,
    temp_threshold_deep_sleep: 25,
    temp_threshold_rem: 20,
    temp_threshold_hibernate: 15,
    idle_threshold_light_sleep: 30,
    idle_threshold_deep_sleep: 60,
    idle_threshold_rem: 90,
    idle_threshold_hibernate: 120,
    monitor_interval_seconds: 60,
  },
}

beforeEach(() => {
  vi.mocked(getSleepSettings).mockResolvedValue(sleepSettingsResponse)
})

describe('SleepSettingsPage 自动睡眠联动显隐', () => {
  it('开启自动睡眠时隐藏手动参数，保留自动相关参数', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const labels = visibleLabels(wrapper)
    for (const label of AUTO_RELEVANT) {
      expect(labels, `${label} 应可见`).to.include(label)
    }
    for (const label of MANUAL_ONLY) {
      expect(labels, `${label} 应隐藏`).to.not.include(label)
    }
  })

  it('关闭自动睡眠后显示全部参数（含手动参数与提示）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // 第一个开关 = 启用自动休眠
    await wrapper.find('button.ant-switch').trigger('click')
    await flushPromises()

    const labels = visibleLabels(wrapper)
    for (const label of [...AUTO_RELEVANT, ...MANUAL_ONLY]) {
      expect(labels, `${label} 应可见`).to.include(label)
    }
    // 手动参数带生效范围提示
    const hintCount = wrapper.findAll('.ant-form-item-extra').length
    expect(hintCount).toBeGreaterThanOrEqual(2)
  })

  it('重新开启后再次隐藏手动参数', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const autoSwitch = wrapper.find('button.ant-switch')
    await autoSwitch.trigger('click')
    await flushPromises()
    await autoSwitch.trigger('click')
    await flushPromises()

    const labels = visibleLabels(wrapper)
    for (const label of MANUAL_ONLY) {
      expect(labels).to.not.include(label)
    }
  })
})

describe('SleepSettingsPage 睡眠节奏卡（阶段推进参数）', () => {
  it('默认温度模式显示温度阈值，隐藏空闲阈值', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const labels = visibleLabels(wrapper)
    expect(labels).to.include('判定模式')
    expect(labels).to.include('阶段监控间隔')
    expect(labels.some((l: string) => l.includes('浅睡眠阶段'))).toBe(true)
    // 温度模式下不显示空闲阈值输入的分钟后缀差异靠模式切换验证
    expect(wrapper.findAll('select.ant-select').length).toBe(1)
  })

  it('切换判定模式为空闲时长后显示分钟阈值输入', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const select = wrapper.find('select.ant-select')
    await select.setValue('time')
    await flushPromises()

    const labels = visibleLabels(wrapper)
    // 空闲阈值的标签同样组合阶段名，切换后 addon 从无变分钟:
    // 4 个空闲阈值 + 核心卡的"触发阈值"输入 = 5 个分钟后缀; 监控间隔带秒后缀
    const addons = wrapper.findAll('.ant-input-number-group-addon').map((a: any) => a.text())
    expect(addons.filter((t: string) => t === '分钟').length).toBe(5)
    expect(addons.filter((t: string) => t === '秒').length).toBe(1)
  })
})

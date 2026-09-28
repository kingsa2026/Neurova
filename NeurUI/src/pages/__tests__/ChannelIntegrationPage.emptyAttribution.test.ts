import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 系统渠道页·空态必须**可归因**（Issue #290 取证报告 §2.7-4 验收线，教义第 5 条同一根因扫荡）。
 *
 * ## 缺陷
 *
 * 本页初值是 `agentId = ref('default')`，但选择器带的是**真实 agent 列表** ——
 * 用户切到「凯蒂」而该 agent 名下没有配置时，整页卡片一律「未启用」，
 * 与"配置读不到"**渲染成同一个样子**。用户读到的结论只有"配置全没了"。
 *
 * Agent 渠道页（本条的第一个命中点）已修；系统页是**同一契约的第二个消费方**：
 * 存量渠道归属 `default`，而本页的用户随时可能正看着别的 agent 视图。
 *
 * ## 判据
 *
 * 按当前 agent 取数为空、且该 agent 不是 `default` 时：
 * - 给出点名说明 + 一键切回默认视图的入口；
 * - 反向控制：`default` 视图下不出现（那里本就是存量归属地，加提示是噪音）。
 */

vi.mock('@/api', () => ({
  api: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }), useRouter: () => ({ push: vi.fn() }) }))

const spies = vi.hoisted(() => ({
  listChannelConfigs: vi.fn(),
}))

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: spies.listChannelConfigs,
  createChannelConfig: vi.fn().mockResolvedValue({}),
  testChannelConfig: vi.fn().mockResolvedValue({ success: true }),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: vi.fn().mockResolvedValue({ code: 0, data: { success: true } }),
  clearChannelQueue: vi.fn().mockResolvedValue({ code: 0, data: { cleared: 0 } }),
  checkChannelConflicts: vi.fn().mockResolvedValue({ code: 0, data: { conflicts: [], checked: 0 } }),
  listPluginChannelSchemas: vi.fn().mockResolvedValue({ data: { schemas: [] } }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  testNegativeScreenPush: vi.fn().mockResolvedValue({ success: true }),
  deleteNegativeScreenConfig: vi.fn().mockResolvedValue({}),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agentOptions: [{ label: '凯蒂', value: '216fb777' }],
    loadAgents: vi.fn(),
    loadWorkflowAgents: vi.fn(),
  }),
}))

// 用**真语言包**而不是手写桩：桩里补了键而真语言包漏了也照样绿。
import zhCN from '@/i18n/locales/zh-CN'
import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': {
          props: ['options', 'value'], emits: ['update:value', 'change'],
          template: `<select class="agent-select" :value="value"
            @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
            <option v-for="o in (options||[])" :key="String(o.value)" :value="String(o.value)">{{ o.label }}</option>
          </select>`,
        },
        'a-spin': { template: '<div><slot/></div>' }, 'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
        'a-modal': { template: '<div><slot/></div>' },
        'a-form': { template: '<form><slot/></form>' }, 'a-form-item': { template: '<div><slot/></div>' },
        'a-switch': { template: '<button/>' }, 'a-input': { template: '<input/>' },
        'a-input-number': { template: '<input/>' }, 'a-tabs': { template: '<div><slot/></div>' },
        'a-tab-pane': { template: '<div><slot/></div>' }, 'a-input-search': { template: '<input/>' },
        'a-badge': { template: '<span><slot/></span>' }, 'a-tooltip': { template: '<span><slot/></span>' },
        NegativeScreenSettings: { template: '<div/>' }, QrcodeAuthBlock: { template: '<div/>' },
      },
    },
  })
}

describe('ChannelIntegrationPage — 空态可归因', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    spies.listChannelConfigs.mockResolvedValue([])
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('切到非 default agent 且取数为空时，给出点名说明与切回入口', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.agent-select').setValue('216fb777')
    await flushPromises()

    const hint = wrapper.find('[data-testid="empty-attribution"]')
    expect(hint.exists(), '空态没有归因说明——用户只能读成"配置全没了"').toBe(true)
    expect(hint.text()).toContain('216fb777')
    expect(wrapper.find('[data-testid="switch-to-default"]').exists()).toBe(true)
  })

  it('切回入口把用户带回默认视图并重新取数', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.agent-select').setValue('216fb777')
    await flushPromises()
    spies.listChannelConfigs.mockClear()

    await wrapper.find('[data-testid="switch-to-default"]').trigger('click')
    await flushPromises()

    expect(spies.listChannelConfigs).toHaveBeenCalledWith('default')
  })

  it('反向控制：该 agent 有配置时不出现空态归因', async () => {
    spies.listChannelConfigs.mockResolvedValue([
      { channel_type: 'feishu', enabled: true, connected: true, extra: {} },
    ])
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.agent-select').setValue('216fb777')
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })

  it('反向控制：default 视图下不出现（那里本就是存量归属地）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })
})

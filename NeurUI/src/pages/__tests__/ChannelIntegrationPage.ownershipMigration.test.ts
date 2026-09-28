import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 系统渠道页 · 归属迁移入口与 403 归因（Issue #290 归属裁决的第二批命中点）。
 *
 * 教义第 5 条：一个断链被点名后，**同一契约的全部消费方**要一并修。
 * Agent 渠道页的空态归因先落，而系统页 `/channels` 是同一契约的另一个消费方
 * ——两页共用 `buildAgentSelectOptions`，用户在这一页切到自己的 agent 视图时，
 * 读到的结论同样只有"配置全没了"。归属迁移的入口与权限不足的归因，
 * 只修一页等于把同一个盲区留在用户更常走的那条入口上。
 */

vi.mock('@/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn(),
  createChannelConfig: vi.fn(),
  testChannelConfig: vi.fn(),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: vi.fn(),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
  listPluginChannelSchemas: vi.fn(),
  migrateAgentChannelConfigs: vi.fn(),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn(),
  testNegativeScreenPush: vi.fn(),
  deleteNegativeScreenConfig: vi.fn(),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))

import { api } from '@/api'
import { listChannelConfigs, migrateAgentChannelConfigs } from '@/api/modules/channel-configs'
import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const AGENTS = [
  { id: '216fb777', name: '凯蒂', status: 'active' },
  { id: 'kai', name: '凯', status: 'active' },
]

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(ChannelIntegrationPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': {
          props: ['options', 'value'],
          emits: ['update:value', 'change'],
          template: `<select class="agent-select" :value="value"
            @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
            <option v-for="opt in (options || [])" :key="String(opt.value)" :value="String(opt.value)">{{ opt.label }}</option>
          </select>`,
        },
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
        'a-form': { template: '<form><slot/></form>' },
        'a-form-item': { props: ['label'], template: '<div><label>{{ label }}</label><slot/></div>' },
        'a-switch': { template: '<button/>' },
        'a-input': { template: '<input/>' },
        'a-input-password': { template: '<input type="password"/>' },
        'a-descriptions': { template: '<div><slot/></div>' },
        'a-descriptions-item': { props: ['label'], template: '<div><b>{{ label }}</b><slot/></div>' },
        GlassInput: { template: '<input/>' },
        NegativeScreenSettings: { template: '<div class="neg-settings"/>' },
      },
    },
  })
}

async function pickAgent(wrapper: ReturnType<typeof mountPage>, value: string) {
  await wrapper.find('.agent-select').setValue(value)
  await flushPromises()
}

describe('ChannelIntegrationPage — 存量归属迁移入口', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(api.get as unknown as { mockImplementation: (fn: (url: string) => Promise<unknown>) => void })
      .mockImplementation((url: string) => {
        if (url === '/agents') return Promise.resolve({ data: AGENTS })
        return Promise.resolve({ data: [] })
      })
    ;(listChannelConfigs as any).mockResolvedValue([])
    ;(migrateAgentChannelConfigs as any).mockResolvedValue({
      success: true, from_agent_id: 'default', to_agent_id: 'kai', migrated: ['feishu', 'qq'],
    })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('切到真实 agent 且无配置时给出迁移入口', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await pickAgent(wrapper, 'kai')

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="migrate-legacy-channels"]').exists()).toBe(true)
  })

  it('点击后按当前身份把 default 的存量搬过来', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await pickAgent(wrapper, 'kai')
    ;(listChannelConfigs as any).mockClear()

    await wrapper.find('[data-testid="migrate-legacy-channels"]').trigger('click')
    await flushPromises()

    expect(migrateAgentChannelConfigs).toHaveBeenCalledWith('default', 'kai')
    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })

  it('403 与「真的没配」在这一页同样可区分', async () => {
    ;(listChannelConfigs as any).mockRejectedValue({
      response: { status: 403, data: { detail: '无权查看智能体『kai』（仅属主或管理员可操作）' } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await pickAgent(wrapper, 'kai')

    const denied = wrapper.find('[data-testid="access-denied"]')
    expect(denied.exists()).toBe(true)
    expect(denied.text()).toContain('无权查看智能体')
    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })
})

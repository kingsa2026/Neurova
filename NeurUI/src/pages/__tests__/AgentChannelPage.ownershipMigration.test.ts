import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'

/**
 * 存量渠道归属迁移的前端入口（Issue #290 归属裁决）。
 *
 * 用户在 Issue 里拍了板：「之前配置的是归属于默认 agent 的，现在可以归属到
 * kai 身上」。后端有了迁移端点，但**用户走不到它**就是断链——本轮把入口落在
 * 用户真正看见存量那一屏（非 default 视图的空态归因块），一键把 default 的
 * 存量搬到自己身上。
 *
 * 另一条同屏判据：**403 必须说出来**。加了归属门之后，非管理员读 default 视图
 * 会拿到 403；若前端仍把它渲染成"尚未配置"，用户就掉进和本 bug 一模一样的
 * 坑——权限不足与"真的没有"在屏幕上不可区分。
 */

const routeState = reactive({ params: { agentId: 'kai' } as Record<string, string> })
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn(),
  createChannelConfig: vi.fn(),
  deleteChannelConfig: vi.fn(),
  migrateAgentChannelConfigs: vi.fn(),
  restartChannelAdapter: vi.fn(),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
  listPluginChannelSchemas: vi.fn(),
  getIngressStats: vi.fn(),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
}))

import {
  listChannelConfigs, migrateAgentChannelConfigs,
} from '@/api/modules/channel-configs'
import AgentChannelPage from '../AgentChannelPage.vue'

// 用**真语言包**而非手写桩：桩里补了键而真语言包漏了键也照样绿——那正是
// "看着咬合、实际没咬住"的老路（与 emptyAttribution 同口径）。
import zhCN from '@/i18n/locales/zh-CN'

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentChannelPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': { props: ['options', 'value'], template: '<select><option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span><slot/></span>' },
        'a-modal': { template: '<div><slot/></div>' },
        'a-form': { template: '<form><slot/></form>' },
        'a-form-item': { template: '<div><slot/></div>' },
        'a-switch': { template: '<button/>' },
        'a-input': { template: '<input/>' },
        QrcodeAuthBlock: { template: '<div/>' },
        NegativeScreenSettings: { template: '<div/>' },
      },
    },
  })
}

describe('AgentChannelPage — 存量归属迁移入口', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    routeState.params.agentId = 'kai'
    ;(listChannelConfigs as any).mockResolvedValue([])
    ;(migrateAgentChannelConfigs as any).mockResolvedValue({
      success: true, from_agent_id: 'default', to_agent_id: 'kai', migrated: ['feishu'],
    })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('非 default 视图为空时给出「搬到我的智能体」入口', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(true)
    const cta = wrapper.find('[data-testid="migrate-legacy-channels"]')
    expect(cta.exists()).toBe(true)
    expect(cta.text().length).toBeGreaterThan(0)
  })

  it('点击后按当前身份发起迁移并刷新本视图', async () => {
    const wrapper = mountPage()
    await flushPromises()
    ;(listChannelConfigs as any).mockClear()

    await wrapper.find('[data-testid="migrate-legacy-channels"]').trigger('click')
    await flushPromises()

    expect(migrateAgentChannelConfigs).toHaveBeenCalledWith('default', 'kai')
    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })

  it('迁移失败（403/409）如实说出原因，不静默', async () => {
    ;(migrateAgentChannelConfigs as any).mockRejectedValue({
      response: { status: 403, data: { detail: '无权删除智能体『default』（仅属主或管理员可操作）' } },
    })
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('[data-testid="migrate-legacy-channels"]').trigger('click')
    await flushPromises()

    const notice = wrapper.find('[data-testid="migrate-error"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('无权删除智能体')
  })

  it('反向控制：default 视图不给迁移入口（那儿就是存量所在地）', async () => {
    routeState.params.agentId = 'default'
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="migrate-legacy-channels"]').exists()).toBe(false)
  })

  it('403 与「真的没配」在屏幕上必须可区分', async () => {
    ;(listChannelConfigs as any).mockRejectedValue({
      response: { status: 403, data: { detail: '无权查看智能体『kai』（仅属主或管理员可操作）' } },
    })
    const wrapper = mountPage()
    await flushPromises()

    const denied = wrapper.find('[data-testid="access-denied"]')
    expect(denied.exists()).toBe(true)
    expect(denied.text()).toContain('无权查看智能体')
    expect(wrapper.find('[data-testid="empty-attribution"]').exists()).toBe(false)
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'

/**
 * 渠道两页的迁移入口改为「打开弹层」（Issue #326 用户口径第 3 条）。
 *
 * 现状：入口是一键把 `default` 整表搬走 —— 源不可选、渠道也不可选，
 * 用户点下去只能全盘接受。用户口径要求弹出层里先选源、再勾选渠道。
 *
 * 判据（同一契约的两个消费方必须同批改，教义第 5 条）：
 * - 点入口只打开弹层，**不发**迁移请求（搬迁是弹层里确认后才发生的事）；
 * - 弹层回报成功后本视图重取（屏幕状态始终来自服务端那唯一的事实源）。
 *
 * 反向控制：若入口仍直接调用 `migrateAgentChannelConfigs`，第一条即红。
 */

const routeState = reactive({ params: { agentId: 'kai' } as Record<string, string> })
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

// 系统页的 agent 身份来自选择器（选项由 agents store 提供）：`/agents` 必须给出
// 真实名单，否则选择器空 → 选中值落成空串 → 拿空身份去请求，测试会掩盖真实缺陷。
vi.mock('@/api', () => ({
  api: {
    get: vi.fn((url: string) => Promise.resolve(
      url === '/agents' ? { data: [{ id: 'kai', name: '凯' }] } : { data: [] },
    )),
    post: vi.fn(), put: vi.fn(), delete: vi.fn(),
  },
}))
vi.mock('@/api/modules/channel-configs', () => ({
  listChannelConfigs: vi.fn().mockResolvedValue([]),
  createChannelConfig: vi.fn(),
  deleteChannelConfig: vi.fn(),
  testChannelConfig: vi.fn(),
  getIngressStats: vi.fn().mockResolvedValue({ enabled: false }),
  restartChannelAdapter: vi.fn(),
  clearChannelQueue: vi.fn(),
  checkChannelConflicts: vi.fn(),
  listPluginChannelSchemas: vi.fn().mockResolvedValue({ data: { schemas: [] } }),
  migrateAgentChannelConfigs: vi.fn().mockResolvedValue({ data: { migrated: ['feishu'] } }),
  listChannelMigrationSources: vi.fn().mockResolvedValue({ data: { sources: [] } }),
}))
vi.mock('@/api/modules/negative-screen', () => ({
  getNegativeScreenConfig: vi.fn().mockResolvedValue({ enabled: false }),
  updateNegativeScreenConfig: vi.fn(),
  testNegativeScreenPush: vi.fn(),
  deleteNegativeScreenConfig: vi.fn(),
  getPushStatistics: vi.fn().mockResolvedValue({ code: 0, data: {} }),
}))

import { listChannelConfigs, migrateAgentChannelConfigs } from '@/api/modules/channel-configs'
import AgentChannelPage from '../AgentChannelPage.vue'
import ChannelIntegrationPage from '../ChannelIntegrationPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-select': { props: ['options', 'value'], emits: ['update:value', 'change'], template: '<select class="agent-select" :value="value" @change="$emit(\'update:value\', $event.target.value); $emit(\'change\', $event.target.value)"><option v-for="o in (options||[])" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div><slot/></div>' },
  'a-switch': { template: '<button/>' },
  'a-input': { template: '<input/>' },
  'a-input-number': { template: '<input/>' },
  'a-modal': { props: ['open'], template: '<div class="ant-modal" v-if="open"><slot/></div>' },
  'a-checkbox': { props: ['value', 'checked'], emits: ['change'], template: '<label class="chk" :data-value="String(value)" :data-checked="checked?\'1\':\'0\'" @click="$emit(\'change\', !checked)"><slot/></label>' },
  GlassInput: { template: '<input/>' },
  QrcodeAuthBlock: { template: '<div/>' },
  NegativeScreenSettings: { template: '<div/>' },
  // 弹层是独立契约（另有 ChannelMigrationDialog.test.ts 判它自己的行为）：
  // 本文件只判**接线**——入口是否打开它、成功后是否触发重取。
  ChannelMigrationDialog: {
    props: ['open', 'targetAgentId'],
    emits: ['close', 'migrated'],
    template: '<div v-if="open" data-testid="migration-dialog" :data-target="targetAgentId"><button data-testid="dialog-emit-migrated" @click="$emit(\'migrated\', { from: \'default\', to: targetAgentId, channels: [\'feishu\'] })">emit</button></div>',
  },
}

function mountPage(component: unknown) {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(component as never, { global: { plugins: [i18n], stubs } })
}

async function pickAgent(wrapper: ReturnType<typeof mountPage>, value: string) {
  await wrapper.find('.agent-select').setValue(value)
  await flushPromises()
}

describe.each([
  ['Agent 渠道页', AgentChannelPage],
  ['系统渠道页', ChannelIntegrationPage],
])('%s — 迁移入口打开弹层', (_label, Page) => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    routeState.params.agentId = 'kai'
    ;(listChannelConfigs as any).mockResolvedValue([])
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('点入口只打开弹层、且弹层拿到当前目标身份，不直接发起迁移', async () => {
    const wrapper = mountPage(Page)
    await flushPromises()
    await pickAgent(wrapper, 'kai')

    const entry = wrapper.find('[data-testid="migrate-legacy-channels"]')
    if (entry.exists()) await entry.trigger('click')
    await flushPromises()

    const dialog = wrapper.find('[data-testid="migration-dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes('data-target')).toBe('kai')
    expect(migrateAgentChannelConfigs).not.toHaveBeenCalled()
  })

  it('弹层回报迁移成功后本视图重取（屏幕状态来自服务端）', async () => {
    const wrapper = mountPage(Page)
    await flushPromises()
    await pickAgent(wrapper, 'kai')

    const entry = wrapper.find('[data-testid="migrate-legacy-channels"]')
    if (entry.exists()) await entry.trigger('click')
    await flushPromises()
    ;(listChannelConfigs as any).mockClear()

    await wrapper.find('[data-testid="dialog-emit-migrated"]').trigger('click')
    await flushPromises()

    expect(listChannelConfigs).toHaveBeenCalledWith('kai')
  })
})

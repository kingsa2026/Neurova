import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

/**
 * 存量渠道迁移弹层（Issue #326 用户口径第 1、2、3 条）。
 *
 * 用户拍的三条：
 *   1. 「选择迁移后，首先选择从哪个 agent 迁移，即源（需要按用户隔离），
 *       现状无选择需要迁移的源」
 *   2. 「选择完源后，选择既有的渠道（勾选/全选），现状无选择需要迁移的渠道」
 *   3. 「前端 UI 功能对齐。选择源及渠道时的弹出层」
 *
 * 现状：两页的入口都是**一键把 default 整表搬走**（`migrateAgentChannelConfigs('default', target)`），
 * 源不可选、渠道也不可选。后端 `channel_types` 早就支持收窄，缺的是把选择权交给用户。
 *
 * 判据（各带反向控制）：
 * - 源清单来自服务端读面（`listChannelMigrationSources`），不前端硬编码 default；
 * - 未选源时不渲染渠道面，也不允许提交（避免"点了没反应"的空动作）；
 * - 勾选/全选后按**选中集合**提交，不整表搬迁；
 * - 一个源都没得选时诚实说明，不给假动作。
 */

const listChannelMigrationSources = vi.fn()
const migrateAgentChannelConfigs = vi.fn()

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelMigrationSources: (...args: unknown[]) => listChannelMigrationSources(...args),
  migrateAgentChannelConfigs: (...args: unknown[]) => migrateAgentChannelConfigs(...args),
}))

import ChannelMigrationDialog from '../ChannelMigrationDialog.vue'
import zhCN from '@/i18n/locales/zh-CN'

function mountDialog(props: Record<string, unknown> = {}) {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(ChannelMigrationDialog, {
    props: { open: true, targetAgentId: 'kai', ...props },
    global: {
      plugins: [i18n],
      stubs: {
        'a-modal': { props: ['open'], template: '<div class="modal" v-if="open"><slot/></div>' },
        'a-select': {
          props: ['value', 'options'],
          emits: ['update:value', 'change'],
          template: `<select class="source-select" :value="value"
            @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
            <option v-for="o in (options || [])" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>`,
        },
        'a-checkbox-group': {
          props: ['value'],
          emits: ['update:value', 'change'],
          template: '<div class="channel-group"><slot/></div>',
        },
        // 真实 a-checkbox 是 click 触发 change（antdv 语义）：桩必须照此发事件，
        // 否则「点了没反应」这类缺陷在测试里恒绿。
        'a-checkbox': {
          props: ['value', 'checked'],
          emits: ['change'],
          template: '<label class="chk" :data-value="String(value)" :data-checked="checked ? \'1\' : \'0\'" @click="$emit(\'change\', !checked)"><slot/></label>',
        },
        'a-spin': { template: '<div><slot/></div>' },
        GlassButton: {
          props: ['disabled'],
          emits: ['click'],
          template: '<button class="gb" :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
        },
      },
    },
  })
}

describe('ChannelMigrationDialog — 源与渠道的选择面', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    listChannelMigrationSources.mockResolvedValue({
      data: {
        sources: [
          { agent_id: 'default', channels: ['feishu', 'telegram'] },
          { agent_id: 'legacy', channels: ['qq'] },
        ],
      },
    })
    migrateAgentChannelConfigs.mockResolvedValue({
      data: { success: true, from_agent_id: 'default', to_agent_id: 'kai', migrated: ['feishu'] },
    })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('打开时按目标身份拉候选源，源选项来自服务端而非硬编码', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    expect(listChannelMigrationSources).toHaveBeenCalledWith('kai')
    const options = wrapper.findAll('.source-select option').map((o) => o.attributes('value'))
    expect(options).toContain('default')
    expect(options).toContain('legacy')
  })

  it('未选源时不渲染渠道面，也不允许提交', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.find('[data-testid="migration-channels"]').exists()).toBe(false)
    expect((wrapper.find('[data-testid="migration-confirm"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('选定源后列出该源的渠道，全选可一次勾上', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('.source-select').setValue('default')
    await flushPromises()

    const box = wrapper.find('[data-testid="migration-channels"]')
    expect(box.exists()).toBe(true)
    expect(box.text()).toContain('feishu')
    expect(box.text()).toContain('telegram')

    await wrapper.find('[data-testid="migration-select-all"]').trigger('click')
    await flushPromises()
    const picked = wrapper.findAll('.chk[data-checked="1"]').map((e) => e.attributes('data-value'))
    expect(picked).toContain('feishu')
    expect(picked).toContain('telegram')
  })

  it('按选中集合提交，不整表搬迁（含反向控制：未勾选的不进请求）', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('.source-select').setValue('default')
    await flushPromises()
    await wrapper.find('.chk[data-value="feishu"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="migration-confirm"]').trigger('click')
    await flushPromises()

    expect(migrateAgentChannelConfigs).toHaveBeenCalledWith('default', 'kai', ['feishu'])
  })

  it('回报的是服务端返回的 migrated，不是本地勾选集合', async () => {
    // 两者在正常情况下相等，但**并发下不等**：列源与提交之间源表可能已被
    // 另一次操作改动（同渠道被别人配了、或已迁走）。屏幕与提示必须来自
    // 服务端那唯一的事实源，本地勾选只是请求参数。
    migrateAgentChannelConfigs.mockResolvedValue({
      data: { success: true, from_agent_id: 'default', to_agent_id: 'kai', migrated: ['feishu'] },
    })
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('.source-select').setValue('default')
    await flushPromises()
    await wrapper.find('[data-testid="migration-select-all"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="migration-confirm"]').trigger('click')
    await flushPromises()

    const events = wrapper.emitted('migrated') as unknown[][]
    expect(events?.length).toBe(1)
    expect((events[0][0] as { channels: string[] }).channels).toEqual(['feishu'])
  })

  it('服务端回报空清单时如实回传（不拿本地勾选冒充已迁）', async () => {
    migrateAgentChannelConfigs.mockResolvedValue({
      data: { success: true, from_agent_id: 'default', to_agent_id: 'kai', migrated: [] },
    })
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('.source-select').setValue('default')
    await flushPromises()
    await wrapper.find('[data-testid="migration-select-all"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="migration-confirm"]').trigger('click')
    await flushPromises()

    const events = wrapper.emitted('migrated') as unknown[][]
    expect((events[0][0] as { channels: string[] }).channels).toEqual([])
  })

  it('没有可迁的源时诚实说明，不给假动作', async () => {
    listChannelMigrationSources.mockResolvedValue({ data: { sources: [] } })
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.find('[data-testid="migration-no-sources"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="migration-confirm"]').exists()).toBe(false)
  })
})

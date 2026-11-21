/**
 * 关键列表渲染回归门（追平计划 E3）—— Agent 列表
 *
 * 抽查结论（组件 → 策略 → 本文件用例）：
 * - AgentListPage.vue（Agent 列表；agentStore 一次全量拉取）：
 *   卡片视图 pagedFilteredAgents = filteredAgents.slice(每页 12) + a-pagination；
 *   表格视图 a-table 客户端分页 pageSize=12。
 *   → 用例 1：500 个 Agent 卡片视图只渲染 12 张卡 + 分页控件存在 + 翻到第 2 页换批仍 12 张；
 *   → 用例 2：500 个 Agent 表格视图只渲染 12 行。
 * - 已知无界登记（未在本文件修）：ChatSessionSidebar.vue 会话列表全量渲染
 *   （getConsoleSessions 未传 limit，侧栏 v-for 全量展开）；SubAgentPanel.vue
 *   事件时间线全量渲染（该组件另有会话在途改造，本轮不动）。
 *
 * 门径：谁移除 slice 分页、或把表格分页改假（pageSize 覆盖全量），本文件即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const exportAgentPackage = vi.fn()
const importAgentPackage = vi.fn()
const downloadManifest = vi.fn()
const exportAgentMigration = vi.fn()
const importAgentMigration = vi.fn()
const downloadMigrationZip = vi.fn()

vi.mock('@/api/modules/agent-package', () => ({
  exportAgentPackage: (...args: unknown[]) => exportAgentPackage(...args),
  importAgentPackage: (...args: unknown[]) => importAgentPackage(...args),
  downloadManifest: (...args: unknown[]) => downloadManifest(...args),
}))

vi.mock('@/api/modules/agent-migration', () => ({
  exportAgentMigration: (...args: unknown[]) => exportAgentMigration(...args),
  importAgentMigration: (...args: unknown[]) => importAgentMigration(...args),
  downloadMigrationZip: (...args: unknown[]) => downloadMigrationZip(...args),
}))

vi.mock('@/api/modules/providers', () => ({ listProviders: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import Antd from 'ant-design-vue'
import AgentListPage from '@/pages/AgentListPage.vue'
import { useAgentStore } from '@/stores/agents'
import zhCN from '@/i18n/locales/zh-CN'

const TOTAL = 500
const PAGE_SIZE = 12

function makeAgents(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `agent-${i}`,
    name: `Agent ${i}`,
    description: `desc-${i}`,
    model: 'm',
    provider: 'p',
    status: 'active',
    avatar: null,
    createdAt: '',
    updatedAt: '',
    config: {
      systemPrompt: '',
      temperature: 0.7,
      maxTokens: 4096,
      topP: 1.0,
      ttsEnabled: false,
      ttsVoice: '',
      ttsSpeed: 1.0,
      ttsPitch: 1.0,
      tools: [],
      skills: [],
    },
  })) as any[]
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

/** 预置 500 个 Agent 后挂载页面（loadAgents 网络失败不清空预置数据，与既有用例同径）。 */
function mountWithAgents(n: number) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentStore()
  store.agents.push(...makeAgents(n))
  // antd 组件在 main.ts 全局注册，测试须同径挂载，a-pagination/a-segmented 才会渲染
  return mount(AgentListPage, { global: { plugins: [i18n, pinia, Antd] } })
}

describe('AgentListPage 关键列表渲染回归门（大数据集不退化为整表渲染）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('卡片视图：500 个 Agent 只渲染一页 12 张卡，分页控件存在且翻页换批', async () => {
    const wrapper = mountWithAgents(TOTAL)
    await flushPromises()

    const cards = wrapper.findAll('.card-grid .nr-glass-card')
    expect(cards.length, `500 个 Agent 卡片视图必须只渲染 ${PAGE_SIZE} 张（分页有界）`).toBe(PAGE_SIZE)

    const pagination = wrapper.find('.card-grid .ant-pagination')
    expect(pagination.exists(), '超过一页时必须渲染分页控件').toBe(true)
    expect(wrapper.find('.ant-pagination-item-2').exists(), '500/12 须存在第 2 页页码').toBe(true)

    // 翻页可用：第 2 页渲染第 13~24 个，仍是有界一页
    await wrapper.find('.ant-pagination-item-2').trigger('click')
    await flushPromises()

    const page2Cards = wrapper.findAll('.card-grid .nr-glass-card')
    expect(page2Cards.length, '翻页后仍须只渲染一页 12 张').toBe(PAGE_SIZE)
    expect(page2Cards[0].find('.nr-glass-card-title').text(), '第 2 页首卡应是第 13 个 Agent').toBe('Agent 12')

    wrapper.unmount()
  })

  it('表格视图：500 个 Agent 只渲染一页 12 行', async () => {
    const wrapper = mountWithAgents(TOTAL)
    await flushPromises()

    // 视图切换器（a-segmented：卡片/表格）切到表格
    const items = wrapper.findAll('.ant-segmented-item')
    const tableItem = items.find((i) => i.text().includes('表格'))
    expect(tableItem, '视图切换器须提供「表格」选项').toBeTruthy()
    await tableItem!.find('input').setValue(true)
    await flushPromises()

    const rows = wrapper.findAll('.ant-table-tbody tr.ant-table-row')
    expect(rows.length, `500 个 Agent 表格视图必须只渲染 ${PAGE_SIZE} 行（客户端分页有界）`).toBe(PAGE_SIZE)
    expect(wrapper.find('.ant-pagination').exists(), '表格视图须保留分页控件').toBe(true)

    wrapper.unmount()
  })
})

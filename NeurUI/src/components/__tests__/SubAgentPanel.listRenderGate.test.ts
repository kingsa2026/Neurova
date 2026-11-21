/**
 * 关键列表渲染回归门（追平计划 E3）—— 子代理事件时间线
 *
 * E3 勘察登记：SubAgentPanel.vue 事件时间线对 timeline 全量 v-for，
 * 长任务事件可达数百条，DOM 行数无界。
 *
 * 修复策略（组件 → 策略 → 本文件用例）：
 * - 时间线默认只渲染最近 50 条（尾部窗口，账本为追加序：尾部=最新）；
 * - 更早的折叠为「查看更早的 {count} 条」入口，点击按批 +50 放量（展开后仍有界）；
 * - 小账本（<50 条）一次全显、无折叠入口；切换子代理窗口归位。
 *
 * 门径：谁把时间线改回全量 v-for、或删掉折叠入口，本文件即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick, reactive } from 'vue'
import SubAgentPanel from '../chat/SubAgentPanel.vue'
import type { SubAgentWindowState } from '../chat/SubAgentPanel.vue'

const getConsoleSubagentEventsMock = vi.fn()
vi.mock('@/api/modules/console', () => ({
  getConsoleSubagentEvents: (...args: unknown[]) => getConsoleSubagentEventsMock(...args),
}))

import zhCN from '@/i18n/locales/zh-CN'

const BATCH = 50

function makeEvents(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    event_id: `e${i}`,
    type: 'spawned',
    subagent_id: 'a1',
    causation_id: '',
    payload: { task: `task-${i}` },
    occurred_at: new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString(),
  }))
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function mountPanel(state: Partial<SubAgentWindowState> = {}) {
  const full: SubAgentWindowState = {
    subagentId: 'a1',
    agentName: '搜索员',
    task: '找资料',
    bodyText: '',
    chunkCount: 0,
    status: 'running',
    report: '',
    error: null,
    ...state,
  }
  return mount(SubAgentPanel, { props: { state: full }, global: { plugins: [i18n] } })
}

/** 打开时间线并等账本渲染完成。 */
async function openTimeline(wrapper: ReturnType<typeof mountPanel>) {
  await wrapper.find('button[title="事件时间线"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SubAgentPanel 事件时间线渲染门（大数据集不退化为整表渲染）', () => {
  it('500 条事件默认只渲染最近 50 条，更早的折叠为展开入口', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: 500, events: makeEvents(500) },
    })
    const wrapper = mountPanel()
    await openTimeline(wrapper)

    const rows = wrapper.findAll('.tl-row')
    expect(rows.length, '500 条事件默认必须只渲染最近 50 条（尾部窗口有界）').toBe(BATCH)
    // 尾部窗口：最新事件在屏、最旧事件折叠
    expect(wrapper.text()).toContain('task-499')
    expect(wrapper.text()).not.toContain('task-0')

    const earlierBtn = wrapper.find('.tl-earlier-btn')
    expect(earlierBtn.exists(), '有更早事件时必须提供折叠展开入口').toBe(true)
    expect(earlierBtn.text()).toContain('450')
    wrapper.unmount()
  })

  it('点击入口按批放量（+50/次），全部展开后入口消失', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: 120, events: makeEvents(120) },
    })
    const wrapper = mountPanel()
    await openTimeline(wrapper)
    expect(wrapper.findAll('.tl-row').length).toBe(BATCH)

    await wrapper.find('.tl-earlier-btn').trigger('click')
    expect(wrapper.findAll('.tl-row').length, '展开一批后应渲染 100 条').toBe(100)
    // 展开后最早的一批事件进入 DOM（120 条取最近 100 → 首条为 task-20）
    expect(wrapper.text()).toContain('task-20')
    expect(wrapper.text()).not.toContain('task-19')

    await wrapper.find('.tl-earlier-btn').trigger('click')
    expect(wrapper.findAll('.tl-row').length, '两批后应渲染全部 120 条').toBe(120)
    expect(wrapper.text()).toContain('task-0')
    expect(wrapper.find('.tl-earlier-btn').exists(), '全部展开后入口应消失').toBe(false)
    wrapper.unmount()
  })

  it('小账本（<50 条）一次全显、无折叠入口', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: 3, events: makeEvents(3) },
    })
    const wrapper = mountPanel()
    await openTimeline(wrapper)
    expect(wrapper.findAll('.tl-row').length).toBe(3)
    expect(wrapper.find('.tl-earlier-btn').exists()).toBe(false)
    wrapper.unmount()
  })

  it('切换子代理后窗口归位到默认批大小', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: 500, events: makeEvents(500) },
    })
    const state = reactive<SubAgentWindowState>({
      subagentId: 'a1', agentName: '搜索员', task: '找资料',
      bodyText: '', chunkCount: 0, status: 'running', report: '', error: null,
    })
    const wrapper = mount(SubAgentPanel, { props: { state }, global: { plugins: [i18n] } })
    await openTimeline(wrapper)
    await wrapper.find('.tl-earlier-btn').trigger('click')
    expect(wrapper.findAll('.tl-row').length).toBe(100)

    // 换子代理（窗口归位，DOM 仍有界）
    state.subagentId = 'a2'
    await nextTick()
    expect(wrapper.findAll('.tl-row').length, '切换子代理后窗口应归位 50').toBe(BATCH)
    wrapper.unmount()
  })
})

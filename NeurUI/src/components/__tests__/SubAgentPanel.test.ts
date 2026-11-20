/**
 * SubAgentPanel — 显示语义（P2-15 数据结构变更防回归）。
 *
 * chunks 数组改为「累积字符串 bodyText + chunkCount 计数」后：
 * 1. running 时渲染累积正文（原 chunks.join('') 等价）；
 * 2. completed 且有 report 时渲染 report（原语义优先级不变）。
 */
import { describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SubAgentPanel from '../chat/SubAgentPanel.vue'
import type { SubAgentWindowState } from '../chat/SubAgentPanel.vue'

// H-4 事件时间线：面板经 console API 拉事件账本——这里 mock 掉网络面
const { getConsoleSubagentEventsMock } = vi.hoisted(() => ({
  getConsoleSubagentEventsMock: vi.fn(),
}))
vi.mock('@/api/modules/console', () => ({
  getConsoleSubagentEvents: getConsoleSubagentEventsMock,
}))

const TIMELINE_EVENTS = [
  { event_id: 'e1', type: 'spawned', subagent_id: 'a1', causation_id: '',
    payload: { task: '找资料' }, occurred_at: '2026-11-17T01:00:00+00:00' },
  { event_id: 'e2', type: 'terminal', subagent_id: 'a1', causation_id: 'e1',
    payload: { status: 'completed' }, occurred_at: '2026-11-17T01:00:05+00:00' },
]

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ui: {
    subagent: '子代理', thinking: '思考中',
    subagentTimeline: '事件时间线', subagentTimelineEmpty: '暂无事件',
    subagentEvSpawned: '派生', subagentEvTerminal: '终态',
    subagentLineage: '谱系（派生链）',
  }, common: { close: '关闭' } } },
})

function mountPanel(state: Partial<SubAgentWindowState>) {
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

describe('SubAgentPanel（P2-15）', () => {
  it('running 时渲染累积正文 bodyText', () => {
    const w = mountPanel({ bodyText: 'hello world', chunkCount: 2, status: 'running' })
    expect(w.text()).toContain('hello world')
  })

  it('completed 且有 report 时优先渲染 report', () => {
    const w = mountPanel({ bodyText: 'partial stream', status: 'completed', report: 'FINAL REPORT' })
    expect(w.text()).toContain('FINAL REPORT')
    expect(w.text()).not.toContain('partial stream')
  })

  it('completed 无 report 时回退累积正文', () => {
    const w = mountPanel({ bodyText: 'stream body', status: 'completed', report: '' })
    expect(w.text()).toContain('stream body')
  })
})

describe('SubAgentPanel 流式输出滚动跟随（2026-09-12 同根因）', () => {
  /** jsdom 无布局引擎：手工注入滚动尺寸（内容 900px / 视口 240px）。 */
  function primeScroll(el: HTMLElement): void {
    Object.defineProperty(el, 'scrollHeight', { value: 900, configurable: true })
    Object.defineProperty(el, 'clientHeight', { value: 240, configurable: true })
  }

  it('chunk 追加后 .panel-content 贴底，最新输出可见', async () => {
    const state = reactive<SubAgentWindowState>({
      subagentId: 'a1', agentName: '搜索员', task: '找资料',
      bodyText: '', chunkCount: 0, status: 'running', report: '', error: null,
    })
    const w = mount(SubAgentPanel, { props: { state }, global: { plugins: [i18n] } })
    const el = w.get('.panel-content').element as HTMLElement
    primeScroll(el)
    expect(el.scrollTop).toBe(0)
    // chunk 到达：真实用法为原地追加（useSubAgentWindows 原地改 bodyText）
    state.bodyText = '新到达的一段输出'
    await nextTick()
    await nextTick()
    expect(el.scrollTop).toBe(900)
  })

  it('用户向上翻阅（距底超阈值）→ 暂停跟随不拽回', async () => {
    const state = reactive<SubAgentWindowState>({
      subagentId: 'a1', agentName: '搜索员', task: '找资料',
      bodyText: '已有内容', chunkCount: 1, status: 'running', report: '', error: null,
    })
    const w = mount(SubAgentPanel, { props: { state }, global: { plugins: [i18n] } })
    const el = w.get('.panel-content').element as HTMLElement
    primeScroll(el)
    // 用户翻到中部（距底 600 > 阈值）
    el.scrollTop = 300
    el.dispatchEvent(new Event('scroll'))
    await nextTick()
    state.bodyText = '已有内容更多输出'
    await nextTick()
    await nextTick()
    expect(el.scrollTop).toBe(300)
  })
})

describe('SubAgentPanel 事件时间线（H-4 闭环读侧）', () => {
  it('点开时间线后拉取并渲染事件账本（因果链序）', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: TIMELINE_EVENTS.length, events: TIMELINE_EVENTS },
    })
    const w = mountPanel({ status: 'running' })
    const btn = w.find('button[title="事件时间线"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(getConsoleSubagentEventsMock).toHaveBeenCalledWith('a1')
    expect(w.find('.panel-timeline').exists()).toBe(true)
    expect(w.text()).toContain('派生')
    expect(w.text()).toContain('终态')
  })

  it('空账本显示暂无事件', async () => {
    getConsoleSubagentEventsMock.mockResolvedValue({
      data: { subagent_id: 'a1', count: 0, events: [] },
    })
    const w = mountPanel({ status: 'completed' })
    await w.find('button[title="事件时间线"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('暂无事件')
  })
})

describe('SubAgentPanel — F5 谱系徽标', () => {
  it('嵌套派生链显示谱系徽标（id 截短 + › 连接，完整链进 title）', () => {
    const w = mountPanel({ agentPath: ['swarm_abcdef123456', 'swarm_leaf'] })
    expect(w.find('.lineage-chip').exists()).toBe(true)
    expect(w.text()).toContain('swarm_abcd…')
    expect(w.text()).toContain('swarm_leaf')
    expect(w.text()).toContain('›')
  })

  it('单元素/缺省谱系不显示徽标（自身路径是噪音）', () => {
    const w1 = mountPanel({ agentPath: ['a1'] })
    expect(w1.find('.lineage-chip').exists()).toBe(false)
    const w2 = mountPanel({})
    expect(w2.find('.lineage-chip').exists()).toBe(false)
  })
})

/**
 * SubAgentPanel — 显示语义（P2-15 数据结构变更防回归）。
 *
 * chunks 数组改为「累积字符串 bodyText + chunkCount 计数」后：
 * 1. running 时渲染累积正文（原 chunks.join('') 等价）；
 * 2. completed 且有 report 时渲染 report（原语义优先级不变）。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SubAgentPanel from '../chat/SubAgentPanel.vue'
import type { SubAgentWindowState } from '../chat/SubAgentPanel.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ui: { subagent: '子代理', thinking: '思考中' }, common: { close: '关闭' } } },
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

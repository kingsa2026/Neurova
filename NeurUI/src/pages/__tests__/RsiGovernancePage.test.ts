import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const listRsiProposals = vi.fn()
const getRsiStatus = vi.fn()
const approveRsiProposal = vi.fn()
const rejectRsiProposal = vi.fn()

vi.mock('@/api/modules/rsiGovernance', () => ({
  getRsiStatus: (...args: unknown[]) => getRsiStatus(...args),
  listRsiProposals: (...args: unknown[]) => listRsiProposals(...args),
  approveRsiProposal: (...args: unknown[]) => approveRsiProposal(...args),
  rejectRsiProposal: (...args: unknown[]) => rejectRsiProposal(...args),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
}))

import RsiGovernancePage from '../RsiGovernancePage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  GlassCard: { props: ['title'], template: '<section><h2>{{ title }}</h2><slot /></section>' },
  AInput: {
    props: ['value', 'placeholder'],
    emits: ['update:value'],
    template: '<input :value="value" :placeholder="placeholder" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  ASelect: { props: ['value'], template: '<select><slot /></select>' },
  ASelectOption: { props: ['value'], template: '<option><slot /></option>' },
  AButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  ATag: { template: '<span><slot /></span>' },
}

const STATUS = {
  agent_id: 'kai',
  iteration_count: 3,
  convergence_status: 'converging',
  deployment_phase: 2,
  phase_advanced: true,
  phase_persisted: false,
  phase_verdict: { state: 'unevidenced', reason: 'experience_quality 缺失' },
  candidates: { generated: 4, pruned: 3, pass_rate: 0.25 },
  rollback_history: [],
  escalation: { verdict: { state: 'passed', reason: '度量失明' }, proposals: ['p-1'], skipped: [] },
}

function factory() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
  return mount(RsiGovernancePage, { global: { plugins: [i18n], stubs } })
}

/**
 * RSI 审批页（工单 011）。
 *
 * 钉的是页面会不会再次变成"看起来一切正常"：读对 agent、503 说清、
 * 批准结果按生效证据回显（注册表没命中就不许显示成功）。
 */
describe('RsiGovernancePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getRsiStatus.mockResolvedValue({ data: { code: 0, data: STATUS } })
    listRsiProposals.mockResolvedValue({
      data: {
        code: 0,
        data: { proposals: [
          { proposal_id: 'p-1', proposal_type: 'skill_manifest', target: 'rsi_escalation_sleep',
            content: 'name: x', risk_level: 'low', status: 'pending', created_at: '2026-09-20' },
        ], state: 'all' },
      },
    })
    approveRsiProposal.mockResolvedValue({
      data: { code: 0, data: { applied: true, applied_skill_id: 'rsi_escalation_sleep', registry_hit: false } },
    })
  })

  it('按选中的 agent 取状态与队列', async () => {
    const wrapper = factory()
    await flushPromises()
    await wrapper.find('[data-testid="rsi-agent"]').setValue('kai')
    await wrapper.find('[data-testid="rsi-reload"]').trigger('click')
    await flushPromises()

    expect(getRsiStatus).toHaveBeenLastCalledWith('kai')
    expect(listRsiProposals).toHaveBeenLastCalledWith({ state: 'all', agentId: 'kai' })
    expect(wrapper.text()).toContain('rsi_escalation_sleep')
  })

  it('阶段未落盘时不能只报"已晋升"', async () => {
    const wrapper = factory()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-phase"]').text()).toBe('2')
    const persisted = wrapper.find('[data-testid="rsi-persisted"]').text()
    expect(persisted).toContain('未落盘')
  })

  it('未装配（503）时显示原因而不是空队列冒充正常', async () => {
    getRsiStatus.mockRejectedValue({ response: { data: { detail: 'agent nobody 上没有 RSI 编排器' } } })
    const wrapper = factory()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-not-ready"]').text()).toContain('没有 RSI 编排器')
    expect(wrapper.find('[data-testid="rsi-status"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rsi-queue"]').text()).not.toContain('rsi_escalation_sleep')
  })

  it('批准时把补交的序列与 agent 一起递给后端，并按生效证据回显', async () => {
    const wrapper = factory()
    await flushPromises()

    await wrapper.find('[data-testid="rsi-sequence-input"]').setValue('read_memory, write_memory')
    await wrapper.find('[data-testid="rsi-approve"]').trigger('click')
    await flushPromises()

    expect(approveRsiProposal).toHaveBeenCalledWith('p-1', {
      approvedBy: 'admin',
      toolSequence: ['read_memory', 'write_memory'],
      agentId: undefined,
    })
    // registry_hit=false ⇒ 必须显式说"下一轮仍看不见"，不能显示成功文案
    expect(wrapper.find('[data-testid="rsi-evidence"]').text()).toContain('回灌未命中')
  })
})

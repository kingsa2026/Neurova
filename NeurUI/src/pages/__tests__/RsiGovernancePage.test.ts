import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const listRsiProposals = vi.fn()
const getRsiStatus = vi.fn()
const approveRsiProposal = vi.fn()
const rejectRsiProposal = vi.fn()
const listRsiGenerations = vi.fn()
const getCurrentBaselineGeneration = vi.fn()
const getRsiGeneration = vi.fn()
const getRsiGenerationLineage = vi.fn()

vi.mock('@/api/modules/rsiGovernance', () => ({
  getRsiStatus: (...args: unknown[]) => getRsiStatus(...args),
  listRsiProposals: (...args: unknown[]) => listRsiProposals(...args),
  approveRsiProposal: (...args: unknown[]) => approveRsiProposal(...args),
  rejectRsiProposal: (...args: unknown[]) => rejectRsiProposal(...args),
  listRsiGenerations: (...args: unknown[]) => listRsiGenerations(...args),
  getCurrentBaselineGeneration: (...args: unknown[]) => getCurrentBaselineGeneration(...args),
  getRsiGeneration: (...args: unknown[]) => getRsiGeneration(...args),
  getRsiGenerationLineage: (...args: unknown[]) => getRsiGenerationLineage(...args),
}))
const getGovernanceSettings = vi.fn()
const updateGovernanceSettings = vi.fn()
const getEvolutionSettings = vi.fn()
const updateEvolutionSettings = vi.fn()

vi.mock('@/api/modules/settings', () => ({
  getGovernanceSettings: (...args: unknown[]) => getGovernanceSettings(...args),
  updateGovernanceSettings: (...args: unknown[]) => updateGovernanceSettings(...args),
}))
vi.mock('@/api/modules/text-evolution', () => ({
  getEvolutionSettings: (...args: unknown[]) => getEvolutionSettings(...args),
  updateEvolutionSettings: (...args: unknown[]) => updateEvolutionSettings(...args),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

import RsiGovernancePage from '../RsiGovernancePage.vue'
import { message } from 'ant-design-vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  GlassCard: { props: ['title'], template: '<section><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' },
  AInput: {
    props: ['value', 'placeholder'],
    emits: ['update:value'],
    template: '<input :value="value" :placeholder="placeholder" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  ASelect: { props: ['value'], template: '<select><slot /></select>' },
  ASelectOption: { props: ['value'], template: '<option><slot /></option>' },
  // emits 必须声明 click：不声明时父级 @click 会作为原生监听**穿透**到根元素，
  // 与模板里的 $emit 叠成两次触发（@click 处理器跑两遍）。
  AButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  ATag: { template: '<span><slot /></span>' },
  AForm: { template: '<form><slot /></form>' },
  AFormItem: { props: ['label'], template: '<div><label>{{ label }}</label><slot /></div>' },
  AInputNumber: {
    props: ['value', 'min', 'max', 'step', 'precision'],
    emits: ['update:value'],
    template: '<input type="number" :value="value" @input="$emit(\'update:value\', $event.target.value === \'\' ? null : Number($event.target.value))" />',
  },
  ASwitch: {
    props: ['checked'],
    emits: ['update:checked'],
    template: '<input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)" />',
  },
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

// 运行参数区（R7）的缺省读数：其余 describe 挂载页面时 loadParams 也会跑，
// 给它们兜底一个空配置，避免未实现 mock 的 undefined 路径。
getGovernanceSettings.mockResolvedValue({ data: { code: 0, data: {} } })
getEvolutionSettings.mockResolvedValue({ data: { code: 0, data: {} } })
updateGovernanceSettings.mockResolvedValue({ data: { code: 0, data: {} } })
updateEvolutionSettings.mockResolvedValue({ data: { code: 0, data: {} } })

// 世代读面（P1-8）兜底：本文件不关心世代区块，给空账本 + 无基线代（404 诚实态）
listRsiGenerations.mockResolvedValue({ data: { code: 0, data: { generations: [], count: 0 } } })
getCurrentBaselineGeneration.mockRejectedValue({
  response: { data: { detail: '尚无已部署的生产基线世代（账本空或没有 deployed 代）' } },
})

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
      // G2 批：agentId 留空时 load 后回填状态面报告的实际 agent（覆写/批准
      // 的目标从此显式）——不再传 undefined 落默认。
      agentId: 'kai',
    })
    // registry_hit=false ⇒ 必须显式说"下一轮仍看不见"，不能显示成功文案
    expect(wrapper.find('[data-testid="rsi-evidence"]').text()).toContain('回灌未命中')
  })
})


describe('RsiGovernancePage — G2 灰度写口（phase_source 呈报＋agent 相位覆写）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getRsiStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { ...STATUS, phase_source: 'override' },
    })
    ;(listRsiProposals as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { proposals: [] } })
  })

  it('状态区呈报相位来源（override/global，不是只有阶段数字）', async () => {
    const wrapper = factory()
    await flushPromises()
    const tag = wrapper.find('[data-testid="rsi-phase-source"]')
    expect(tag.exists()).toBe(true), '相位来源读数（G2：override/global）未呈报'
    expect(tag.text()).not.toBe(''), '相位来源 tag 渲染为空'
  })

})


describe('RsiGovernancePage — 运行参数区（R7）', () => {
  const GOV_SETTINGS = {
    rsi_phase: 2,
    metacog_gate_enabled: true,
    rsi_phase_min_applied: { '2': 3, '3': 10 },
    rsi_canary_window_seconds: 600,
    rsi_canary_rollback_thresholds: { max_error_rate: 0.3, min_success_rate_drop: 0.2 },
    rsi_phase_overrides: { kai: 3 },
  }

  beforeEach(() => {
    vi.clearAllMocks()
    getRsiStatus.mockResolvedValue({ data: { code: 0, data: STATUS } })
    listRsiProposals.mockResolvedValue({ data: { code: 0, data: { proposals: [], state: 'all' } } })
    getGovernanceSettings.mockResolvedValue({ data: { code: 0, data: GOV_SETTINGS } })
    getEvolutionSettings.mockResolvedValue({
      data: { code: 0, data: { rsi_rollback_persistence_enabled: false } },
    })
    updateGovernanceSettings.mockResolvedValue({ data: { code: 0, data: {} } })
    updateEvolutionSettings.mockResolvedValue({ data: { code: 0, data: {} } })
  })

  /** DOMWrapper.element 的类型是宽泛 VueNode；控件桩都渲染成原生 input，收口到这里断言。 */
  function inputOf(wrapper: ReturnType<typeof factory>, selector: string): HTMLInputElement {
    return wrapper.find(selector).element as HTMLInputElement
  }

  it('渲染治理设置与进化设置的当前读数（含只读覆写）', async () => {
    const wrapper = factory()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-params"]').exists()).toBe(true)
    expect(inputOf(wrapper, '[data-testid="rsi-param-phase"]').value).toBe('2')
    expect(inputOf(wrapper, '[data-testid="rsi-param-metacog"]').checked).toBe(true)
    expect(inputOf(wrapper, '[data-testid="rsi-param-rollback-persistence"]').checked).toBe(false)
    expect(inputOf(wrapper, '[data-testid="rsi-param-canary-window"]').value).toBe('600')
    expect(inputOf(wrapper, '[data-testid="rsi-param-max-error-rate"]').value).toBe('0.3')
    expect(inputOf(wrapper, '[data-testid="rsi-param-min-success-drop"]').value).toBe('0.2')
    expect(wrapper.find('[data-testid="rsi-param-min-applied-2"]').exists()).toBe(true)
    expect(inputOf(wrapper, '[data-testid="rsi-param-min-applied-3"]').value).toBe('10')
    // 覆写只读展示（写入口不在这里）
    expect(wrapper.find('[data-testid="rsi-overrides-readonly"]').text()).toContain('kai=3')
  })

  it('提交修改分流到治理设置与进化设置两端点', async () => {
    const wrapper = factory()
    await flushPromises()

    await wrapper.find('[data-testid="rsi-param-phase"]').setValue(1)
    await wrapper.find('[data-testid="rsi-param-canary-window"]').setValue(120)
    await wrapper.find('[data-testid="rsi-param-max-error-rate"]').setValue(0.5)
    await wrapper.find('[data-testid="rsi-param-metacog"]').setValue(false)
    await wrapper.find('[data-testid="rsi-param-rollback-persistence"]').setValue(true)
    await wrapper.find('[data-testid="rsi-params-save"]').trigger('click')
    await flushPromises()

    expect(updateGovernanceSettings).toHaveBeenCalledTimes(1)
    expect(updateGovernanceSettings).toHaveBeenCalledWith({
      rsi_phase: 1,
      metacog_gate_enabled: false,
      rsi_phase_min_applied: { '2': 3, '3': 10 },
      rsi_canary_window_seconds: 120,
      rsi_canary_rollback_thresholds: { max_error_rate: 0.5, min_success_rate_drop: 0.2 },
    })
    expect(updateEvolutionSettings).toHaveBeenCalledWith({
      rsi_rollback_persistence_enabled: true,
    })
    expect(message.success).toHaveBeenCalled()
  })

  it('越界值前端拦截：不提交并点名错误', async () => {
    const wrapper = factory()
    await flushPromises()

    await wrapper.find('[data-testid="rsi-param-phase"]').setValue(9)
    await wrapper.find('[data-testid="rsi-params-save"]').trigger('click')
    await flushPromises()

    expect(updateGovernanceSettings).not.toHaveBeenCalled()
    expect(updateEvolutionSettings).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalled()
  })

  it('运行参数未加载成功时阻止提交（防默认值覆盖线上配置）', async () => {
    getGovernanceSettings.mockRejectedValue(new Error('boom'))
    const wrapper = factory()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-params-not-loaded"]').exists()).toBe(true)
    await wrapper.find('[data-testid="rsi-params-save"]').trigger('click')
    await flushPromises()

    expect(updateGovernanceSettings).not.toHaveBeenCalled()
    expect(updateEvolutionSettings).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
  })
})

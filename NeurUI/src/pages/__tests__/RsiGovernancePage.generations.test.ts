import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// ---------------------------------------------------------------------------
// P1-8 世代谱系读面（接 P1-5 四条端点）：
//   GET /v1/governance/rsi/generations            列表（limit/status 过滤）
//   GET /v1/governance/rsi/generations/current    当前生产基线代
//   GET /v1/governance/rsi/generations/{no}       单代详情
//   GET /v1/governance/rsi/generations/{no}/lineage 谱系回溯链
// 钉的是读面诚实：503 未装配不冒充空账本、404 基线不造数、三态徽标不折叠。
// ---------------------------------------------------------------------------

const listRsiGenerations = vi.fn()
const getCurrentBaselineGeneration = vi.fn()
const getRsiGeneration = vi.fn()
const getRsiGenerationLineage = vi.fn()
const getRsiStatus = vi.fn()
const listRsiProposals = vi.fn()
const approveRsiProposal = vi.fn()
const rejectRsiProposal = vi.fn()
const approveImproverUpgrade = vi.fn()

vi.mock('@/api/modules/rsiGovernance', () => ({
  getRsiStatus: (...args: unknown[]) => getRsiStatus(...args),
  listRsiProposals: (...args: unknown[]) => listRsiProposals(...args),
  approveRsiProposal: (...args: unknown[]) => approveRsiProposal(...args),
  rejectRsiProposal: (...args: unknown[]) => rejectRsiProposal(...args),
  approveImproverUpgrade: (...args: unknown[]) => approveImproverUpgrade(...args),
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
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  GlassCard: { props: ['title'], template: '<section><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' },
  AInput: {
    props: ['value', 'placeholder'],
    emits: ['update:value'],
    template: '<input :value="value" :placeholder="placeholder" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  ASelect: {
    props: ['value'],
    emits: ['update:value'],
    template: '<select :value="value" @change="$emit(\'update:value\', $event.target.value)"><slot /></select>',
  },
  ASelectOption: { props: ['value'], template: '<option :value="value"><slot /></option>' },
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

/** 列表条目形状 = governance.py `_generationSummary`（全量档案只在详情面出街） */
function summaryOf(no: number, overrides: Record<string, unknown> = {}) {
  return {
    generationNo: no,
    parentNo: no > 1 ? no - 1 : null,
    status: 'deployed',
    decision: { kind: 'auto', approver: '', reason: '' },
    promotedAt: '2026-11-21T10:00:00+00:00',
    ...overrides,
  }
}

/** 详情形状 = generation_ledger.py `EvolutionGeneration.to_dict()` */
function detailOf(no: number, overrides: Record<string, unknown> = {}) {
  return {
    generationNo: no,
    parentNo: no > 1 ? no - 1 : null,
    basisCommit: 'abc1234',
    createdAt: '2026-11-21T09:00:00+00:00',
    signals: [{ kind: 'lesson', ref: 'lesson-7', summary: 'web_fetch 连续失败' }],
    changes: [{ targetId: 'rsi_escalation_sleep', kind: 'param', ref: 'candidate-3', rationale: '提升决策档通过率' }],
    verdicts: {
      g0: { state: 'passed', reason: '' },
      g1: { state: 'passed', reason: '' },
      g2: { state: 'failed', reason: '决策档回退' },
      g3: { state: 'unevidenced', reason: '无 A/B 数据' },
    },
    decision: { kind: 'approval', approver: 'admin', reason: '' },
    deployment: {
      promotedAt: '2026-11-21T10:00:00+00:00',
      canaryConclusion: 'rollback: 错误率越界',
      rolledBackTo: no - 1,
      canaryStartedAt: '2026-11-21T09:30:00+00:00',
    },
    status: 'rolledBack',
    ...overrides,
  }
}

function mountGenPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
  return mount(RsiGovernancePage, { global: { plugins: [i18n], stubs } })
}

// 页面挂载即跑的其余读面兜底（本文件只关心世代区块）
getRsiStatus.mockResolvedValue({ data: { code: 0, data: { agent_id: 'kai', deployment_phase: 1, candidates: { pass_rate: 0 } } } })
listRsiProposals.mockResolvedValue({ data: { code: 0, data: { proposals: [], state: 'all' } } })
getGovernanceSettings.mockResolvedValue({ data: { code: 0, data: {} } })
getEvolutionSettings.mockResolvedValue({ data: { code: 0, data: {} } })

beforeEach(() => {
  vi.clearAllMocks()
  getRsiStatus.mockResolvedValue({ data: { code: 0, data: { agent_id: 'kai', deployment_phase: 1, candidates: { pass_rate: 0 } } } })
  listRsiProposals.mockResolvedValue({ data: { code: 0, data: { proposals: [], state: 'all' } } })
  listRsiGenerations.mockResolvedValue({
    data: { code: 0, data: { generations: [summaryOf(3), summaryOf(2), summaryOf(1, { status: 'proposed', promotedAt: '' })], count: 3 } },
  })
  getCurrentBaselineGeneration.mockResolvedValue({ data: { code: 0, data: detailOf(3, { status: 'deployed' }) } })
  getRsiGeneration.mockImplementation((no: number) =>
    Promise.resolve({ data: { code: 0, data: detailOf(no) } }))
  getRsiGenerationLineage.mockImplementation((no: number) =>
    Promise.resolve({ data: { code: 0, data: { lineage: [detailOf(no), detailOf(no - 1), detailOf(no - 2)] } } }))
})

describe('RsiGovernancePage — 世代谱系读面（P1-8）', () => {
  it('渲染世代列表（序号/父代/状态/裁决/晋升时间）与当前基线代', async () => {
    const wrapper = mountGenPage()
    await flushPromises()

    const table = wrapper.find('[data-testid="rsi-gen-table"]')
    expect(table.exists()).toBe(true), '世代列表表未渲染'
    expect(wrapper.find('[data-testid="rsi-gen-row-3"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="rsi-gen-row-1"]').exists()).toBe(true)
    // 列表面只出摘要字段，不含详情面的变更目标
    expect(table.text()).not.toContain('rsi_escalation_sleep')
    // 当前基线代
    const baseline = wrapper.find('[data-testid="rsi-gen-baseline"]')
    expect(baseline.exists()).toBe(true)
    expect(baseline.text()).toContain('3')
  })

  it('列表行呈报状态徽标与裁决（审批人可见）', async () => {
    const wrapper = mountGenPage()
    await flushPromises()

    const badge = wrapper.find('[data-testid="rsi-gen-status-badge-3"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).not.toBe('')
    const row = wrapper.find('[data-testid="rsi-gen-row-3"]')
    expect(row.text()).toContain('3') // 序号
    expect(row.text()).toContain('2') // 父代
  })

  it('limit 与 status 过滤随刷新传给列表端点', async () => {
    const wrapper = mountGenPage()
    await flushPromises()
    listRsiGenerations.mockClear()

    await wrapper.find('[data-testid="rsi-gen-status"]').setValue('deployed')
    await wrapper.find('[data-testid="rsi-gen-limit"]').setValue(5)
    await wrapper.find('[data-testid="rsi-gen-reload"]').trigger('click')
    await flushPromises()

    expect(listRsiGenerations).toHaveBeenLastCalledWith({ limit: 5, status: 'deployed', agentId: 'kai' })
  })

  it('详情展开拉取单代详情与谱系链，呈报信号/变更/三态门禁/部署', async () => {
    const wrapper = mountGenPage()
    await flushPromises()

    await wrapper.find('[data-testid="rsi-gen-detail-3"]').trigger('click')
    await flushPromises()

    expect(getRsiGeneration).toHaveBeenCalledWith(3, 'kai')
    expect(getRsiGenerationLineage).toHaveBeenCalledWith(3, 'kai')

    const detail = wrapper.find('[data-testid="rsi-gen-detail"]')
    expect(detail.exists()).toBe(true)
    // 信号摘要（为什么改）
    expect(wrapper.find('[data-testid="rsi-gen-signals"]').text()).toContain('web_fetch 连续失败')
    // 变更（改了什么）
    expect(wrapper.find('[data-testid="rsi-gen-changes"]').text()).toContain('rsi_escalation_sleep')
    // 三态门禁徽标逐门呈报，不折叠
    const g0 = wrapper.find('[data-testid="rsi-gen-verdict-g0"]')
    const g2 = wrapper.find('[data-testid="rsi-gen-verdict-g2"]')
    const g3 = wrapper.find('[data-testid="rsi-gen-verdict-g3"]')
    expect(g0.exists()).toBe(true)
    expect(g2.exists()).toBe(true)
    expect(g3.exists()).toBe(true)
    expect(g0.text()).not.toBe(g2.text())
    expect(g2.text()).not.toBe(g3.text())
    // 裁决审批人与部署结论
    expect(wrapper.find('[data-testid="rsi-gen-decision"]').text()).toContain('admin')
    const deployment = wrapper.find('[data-testid="rsi-gen-deployment"]')
    expect(deployment.text()).toContain('rollback')
    expect(deployment.text()).toContain('2') // rolledBackTo
    // 谱系链（含祖先代）
    const lineage = wrapper.find('[data-testid="rsi-gen-lineage"]')
    expect(lineage.exists()).toBe(true)
    expect(lineage.text()).toContain('2')
  })

  it('账本空 → 空态点名（不冒充 503，也不造数据）', async () => {
    listRsiGenerations.mockResolvedValue({ data: { code: 0, data: { generations: [], count: 0 } } })
    const wrapper = mountGenPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-gen-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="rsi-gen-table"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rsi-gen-not-ready"]').exists()).toBe(false)
  })

  it('世代管线未装配（503）→ 诚实呈现原因，不出空表', async () => {
    listRsiGenerations.mockRejectedValue({
      response: { data: { detail: 'agent kai 上世代管线未装配：该 agent 的 RSI 未挂接世代编排器（P1-3 管线缺席，读面不造数据）' } },
    })
    const wrapper = mountGenPage()
    await flushPromises()

    const notReady = wrapper.find('[data-testid="rsi-gen-not-ready"]')
    expect(notReady.exists()).toBe(true)
    expect(notReady.text()).toContain('未装配')
    expect(wrapper.find('[data-testid="rsi-gen-table"]').exists()).toBe(false)
  })

  it('尚无已部署基线代（404）→ 基线行如实说"尚无"，不拿最大序号充数', async () => {
    getCurrentBaselineGeneration.mockRejectedValue({
      response: { data: { detail: '尚无已部署的生产基线世代（账本空或没有 deployed 代）' } },
    })
    const wrapper = mountGenPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="rsi-gen-baseline"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rsi-gen-baseline-none"]').exists()).toBe(true)
  })

  it('详情拉取失败 → 展开区呈现失败原因，不留空白假成功', async () => {
    getRsiGeneration.mockRejectedValue({ response: { data: { detail: '世代不存在: 3' } } })
    const wrapper = mountGenPage()
    await flushPromises()

    await wrapper.find('[data-testid="rsi-gen-detail-3"]').trigger('click')
    await flushPromises()

    const detail = wrapper.find('[data-testid="rsi-gen-detail-error"]')
    expect(detail.exists()).toBe(true)
    expect(detail.text()).toContain('世代不存在')
  })
})

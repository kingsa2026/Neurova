/**
 * AgentSkillPage — 提案详情里的「双臂核验」两栏（§8 前置 2 / 票面 Task 4 的读侧）
 *
 * 这个端点自落地起零消费者（台账 §6-111），补上读侧后本文件锁住四件容易悄悄退让的事：
 *  1. 进哪一栏由**报告里的** `executor_kind` 决定，不由"我发了什么请求"决定——
 *     端点/服务端在拿不到 agent 时会 409，而若哪天改成静默回落，标注必须跟着事实走；
 *  2. 两栏并存时各自的数字都在场，不合并成一个数（模拟面与真轨迹面量的是不同的事）；
 *  3. 没有候选正文时不发请求（后端会 422，前端先说清楚）；
 *  4. 切到另一条提案时清空上一臂读数，否则 A 提案的核验结果会挂到 B 提案上。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { apiMock } = vi.hoisted(() => {
  const m: Record<string, any> = {
    getAgentSkills: vi.fn().mockResolvedValue([]),
    listConsolidationPlans: vi.fn().mockResolvedValue({ code: 0, data: [] }),
  }
  return { apiMock: m }
})
vi.mock('@/api/modules/skill-pool', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(apiMock).map((k) => [k, (...a: unknown[]) => apiMock[k](...a)])),
}))

const { evolutionMock } = vi.hoisted(() => {
  const m: Record<string, any> = {
    getLifecycleUsage: vi.fn().mockResolvedValue({ data: { counts: {}, skills: [] } }),
    getEvolutionSettings: vi.fn().mockResolvedValue({ data: {} }),
    listProposals: vi.fn().mockResolvedValue({ data: [] }),
    getProposal: vi.fn(),
    approveProposal: vi.fn(),
    rejectProposal: vi.fn(),
    evolveSkill: vi.fn(),
    pinSkill: vi.fn(),
    runLifecycleSweep: vi.fn(),
    updateEvolutionSettings: vi.fn(),
    abCompareSkills: vi.fn(),
  }
  return { evolutionMock: m }
})
vi.mock('@/api/modules/text-evolution', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(evolutionMock).map((k) => [k, (...a: unknown[]) => evolutionMock[k](...a)])),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import AgentSkillPage from '../AgentSkillPage.vue'

const PROPOSAL = {
  proposal_id: 'evo_1',
  skill_id: 's1',
  artifact_type: 'skill',
  status: 'pending',
  holdout_before: 0.4,
  holdout_after: 0.6,
  iterations_run: 3,
  created_at: '',
  decided_at: '',
  baseline_text: '基线正文',
  improved_text: '候选正文',
}

const REPORT = (kind: string, over: Record<string, unknown> = {}) => ({
  code: 0,
  data: {
    task_split: 'heldout',
    n: 2,
    baseline_avg: 0.2,
    candidate_avg: kind === 'real_agent' ? 0.35 : 0.9,
    delta: kind === 'real_agent' ? 0.15 : 0.7,
    per_task: [
      { task_input: 'HELD0', baseline: 0.2, candidate: kind === 'real_agent' ? 0.3 : 0.9 },
      { task_input: 'HELD1', baseline: 0.2, candidate: kind === 'real_agent' ? 0.4 : 0.9 },
    ],
    executor_kind: kind,
    ...over,
  },
})

const messages = {
  common: { refresh: '刷新', save: '保存', cancel: '取消' },
  skill: {
    totalSkills: '技能总数', enabledSkills: '已启用', executionCount: '执行次数',
    searchPlaceholder: '搜索', enabled: '已启用', disabled: '已禁用', executions: '次',
    execute: '执行', noSkills: '暂无技能', loadError: '加载失败', installSuccess: '已安装',
    importFromMarket: '导入', noMarketSkills: '无', executeSkill: '执行', arguments: '参数',
    argsPlaceholder: 'JSON', executeSuccess: '成功', executeError: '失败', install: '安装',
    enabledSuccess: 'ok', disabledSuccess: 'ok', toggleError: '失败', pushToMine: '推送',
    pushSubmitted: '已推送', pushError: '失败', marketSearchPlaceholder: '搜索',
  },
  skillEvo: {
    proposals: '待审提案', settings: '进化设置', runSweep: '扫描', pinned: '已钉住',
    pin: '钉住', unpin: '解钉', pinSuccess: 'ok', pinError: '失败', evolve: '进化',
    textEvolution: '文本进化', textEvolutionHint: 'h', lifecycleSweep: '扫描',
    lifecycleSweepHint: 'h', sweepInterval: '间隔', saveSuccess: 'ok', saveError: '失败',
    runEvolve: '进化', iterations: '轮数', datasetSource: '评测集', sourceAuto: '自动',
    sourceGolden: '手写', sourceMined: '挖掘', sourceSynthetic: '合成', evolveError: '失败',
    accepted: '通过', noChange: '无变化', noProposals: '无', view: '查看',
    approve: '批准', reject: '拒绝', approved: 'ok', rejectedOk: 'ok', decideError: '失败',
    proposalDetail: '提案详情', holdout: '留出集', iterationsUnit: '轮', baseline: '改进前',
    improved: '改进后', loadError: '加载失败', stateActive: '活跃', stateStale: '陈旧',
    stateArchived: '归档', agentCreated: '智能体创建',
    consolidation: '技能合并', consolidationHint: 'h', consolidationEmpty: '无',
    consolidationAbsorbed: '成员', consolidationApprove: '批准', consolidationApproved: 'ok',
    consolidationRejected: 'ok', consolidationError: '失败',
    consolidationBasisIdentity: '身份', consolidationBasisStructure: '序列',
    consolidationBasisNamePrefix: '前缀',
    archive: '归档', archiveTitle: '归档', archiveEmpty: '无', archiveVersion: '版本',
    archiveArchivedAt: '时间', rollback: '回滚', rollbackConfirm: '确认？',
    rollbackDone: 'ok', rollbackError: '失败', archiveLoadError: '失败',
    abVerify: '双臂核验', abHint: '同一任务集对照两份正文', abRunSimulated: '跑模拟面',
    abRunReal: '跑真轨迹面', abExecutor: '执行面', abKindSimulated: '模拟面',
    abKindReal: '真轨迹面', abMetricN: '任务数', abMetricBaseline: '基线',
    abMetricCandidate: '候选', abMetricDelta: '差', abTaskCol: '任务', abFailed: '核验失败',
    abKindMismatch: '执行面与所选不符', abNoCandidate: '无候选正文',
    auditRun: '进化审计运行', auditRunCases: '留出侧逐例读数',
    auditRunJudgeDown: '判分不可用：本轮任何增益都不可信',
    auditRunMissing: '运行记录不见了', auditRunNoneRecorded: '本轮未落运行记录',
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(AgentSkillPage, {
    props: { agentId: 'agent-1' },
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { template: '<div><slot /></div>' },
        GlassCard: { props: ['title', 'subtitle'], template: '<div class="gc"><h3>{{ title }}</h3><span>{{ subtitle }}</span><slot /></div>' },
        GlassButton: { props: ['variant', 'size', 'loading', 'disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
        GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div />' },
        'a-input-search': { template: '<input />' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-empty': { props: ['description'], template: '<div class="empty">{{ description }}</div>' },
        'a-tag': { template: '<span class="tag"><slot /></span>' },
        'a-switch': { template: '<button class="sw" />' },
        'a-modal': { props: ['open', 'title'], template: '<div class="modal"><span class="modal-title">{{ title }}</span><slot /></div>' },
        'a-form': { template: '<div><slot /></div>' },
        'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
        'a-textarea': { template: '<textarea />' },
        'a-input': { template: '<input />' },
        'a-input-number': { template: '<input type="number" />' },
        'a-select': { template: '<div><slot /></div>' },
        'a-select-option': { template: '<div><slot /></div>' },
        'a-alert': { props: ['message'], template: '<div>{{ message }}</div>' },
        'a-row': { template: '<div><slot /></div>' },
        'a-col': { template: '<div><slot /></div>' },
      },
    },
  })
}

async function openDetail(proposal: Record<string, unknown> = PROPOSAL) {
  evolutionMock.getProposal.mockResolvedValue({ code: 0, data: proposal })
  const wrapper = mountPage()
  await flushPromises()
  await (wrapper.vm as any).viewProposal({ proposal_id: proposal.proposal_id })
  await flushPromises()
  return wrapper
}

describe('AgentSkillPage — 双臂核验两栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
    evolutionMock.getLifecycleUsage.mockResolvedValue({ data: { counts: {}, skills: [] } })
    evolutionMock.getEvolutionSettings.mockResolvedValue({ data: {} })
    evolutionMock.listProposals.mockResolvedValue({ data: [] })
  })

  it('提案详情渲染出核验区与两个入口', async () => {
    const wrapper = await openDetail()
    const text = wrapper.text()
    expect(text).toContain('双臂核验')
    expect(text).toContain('跑模拟面')
    expect(text).toContain('跑真轨迹面')
  })

  it('模拟臂不带 real_trajectory，真臂必须带（两面的成本与口径不同，不许默认全跑）', async () => {
    evolutionMock.abCompareSkills.mockResolvedValue(REPORT('simulated'))
    const wrapper = await openDetail()
    await (wrapper.vm as any).runAbArm('simulated')
    await flushPromises()
    expect(evolutionMock.abCompareSkills).toHaveBeenCalledWith(
      'agent-1',
      { skill_id: 's1', candidate_text: '候选正文', real_trajectory: false },
    )

    evolutionMock.abCompareSkills.mockResolvedValue(REPORT('real_agent'))
    await (wrapper.vm as any).runAbArm('real_agent')
    await flushPromises()
    const last = evolutionMock.abCompareSkills.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(last.real_trajectory).toBe(true)
  })

  it('进栏由报告里的 executor_kind 决定：请求真臂却回 simulated ⇒ 落模拟栏并显式报错', async () => {
    evolutionMock.abCompareSkills.mockResolvedValue(REPORT('simulated'))
    const wrapper = await openDetail()
    await (wrapper.vm as any).runAbArm('real_agent')
    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.abReports.simulated).not.toBeNull()
    expect(vm.abReports.real_agent).toBeNull()
    expect(vm.abError).toContain('执行面与所选不符')
    expect(wrapper.text()).toContain('执行面与所选不符')
  })

  it('两栏并存且数字不合并：同一对正文在两个面给出不同的差', async () => {
    evolutionMock.abCompareSkills.mockResolvedValueOnce(REPORT('simulated'))
    const wrapper = await openDetail()
    await (wrapper.vm as any).runAbArm('simulated')
    await flushPromises()
    evolutionMock.abCompareSkills.mockResolvedValueOnce(REPORT('real_agent'))
    await (wrapper.vm as any).runAbArm('real_agent')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('模拟面')
    expect(text).toContain('真轨迹面')
    // 两栏各自的候选均分（0.9 与 0.35）必须同时在场——合并或覆盖成一个就看不出两面在说不同的话
    expect(text).toContain('0.9')
    expect(text).toContain('0.35')
    expect((wrapper.vm as any).abError).toBe('')
  })

  it('没有候选正文时不发请求，直接说明原因', async () => {
    const wrapper = await openDetail({ ...PROPOSAL, improved_text: '   ' })
    await (wrapper.vm as any).runAbArm('simulated')
    await flushPromises()
    expect(evolutionMock.abCompareSkills).not.toHaveBeenCalled()
    expect((wrapper.vm as any).abError).toContain('无候选正文')
  })

  it('切到另一条提案时清空上一臂读数（不把 A 的核验结果挂到 B 上）', async () => {
    evolutionMock.abCompareSkills.mockResolvedValue(REPORT('simulated'))
    const wrapper = await openDetail()
    await (wrapper.vm as any).runAbArm('simulated')
    await flushPromises()
    expect((wrapper.vm as any).abReports.simulated).not.toBeNull()

    evolutionMock.getProposal.mockResolvedValue({
      code: 0,
      data: { ...PROPOSAL, proposal_id: 'evo_2', skill_id: 's2' },
    })
    await (wrapper.vm as any).viewProposal({ proposal_id: 'evo_2' })
    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.abReports.simulated).toBeNull()
    expect(vm.abReports.real_agent).toBeNull()
    expect(vm.abError).toBe('')
    expect(wrapper.text()).not.toContain('执行面: 模拟面')
  })

  it('端点报错时把后端的 detail 原样交代出来，不吞成"失败"了事', async () => {
    evolutionMock.abCompareSkills.mockRejectedValue({
      response: { data: { detail: 'agent「agent-1」不在线，无法跑真轨迹双臂' } },
    })
    const wrapper = await openDetail()
    await (wrapper.vm as any).runAbArm('real_agent')
    await flushPromises()
    expect((wrapper.vm as any).abError).toContain('不在线')
    expect(wrapper.text()).toContain('不在线')
  })
})

/**
 * 提案详情把那次进化的审计运行读出来（§6-95 后半：`runs/*.json` 此前只写不读）。
 *
 * 三态必须**各自出声**：取回了 ⇒ 逐例读数；提案带着 run_id 而文件不见了 ⇒ 明说；
 * 本轮压根没记 ⇒ 也明说。静默省略等于把审计面的缺失洗成"看起来没这回事"。
 */
describe('AgentSkillPage — 提案详情读那次审计运行', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
    evolutionMock.getLifecycleUsage.mockResolvedValue({ data: { counts: {}, skills: [] } })
    evolutionMock.getEvolutionSettings.mockResolvedValue({ data: {} })
    evolutionMock.listProposals.mockResolvedValue({ data: [] })
  })

  const withRun = (over: Record<string, unknown>) => ({
    ...PROPOSAL,
    run_id: 'run_20261010T040000_abc123',
    evolution_run: {
      run_id: 'run_20261010T040000_abc123',
      at: '2026-10-10T04:00:00+00:00',
      skill_id: 's1',
      artifact_type: 'skill',
      iterations_run: 3,
      holdout_before: 0.4,
      holdout_after: 0.6,
      judge_available: true,
      // 线上键名（`EvolutionRunResult.to_dict()`），不是 dataclass 字段名。
      holdout_cases: {
        HELD0: { baseline: 0.2, candidate: 0.3 },
        HELD1: { baseline: 0.2, candidate: 0.9 },
      },
    },
    evolution_run_status: 'attached',
    ...over,
  })

  it('取回运行时把留出侧逐例读数摆在审批人面前', async () => {
    const wrapper = await openDetail(withRun({}))
    const text = wrapper.text()
    expect(text).toContain('进化审计运行')
    expect(text).toContain('留出侧逐例读数')
    // 均分之外的那一半：HELD0 只涨了一点、HELD1 涨得多——集级均值会把两者混成一个数
    expect(text).toContain('HELD0')
    expect(text).toContain('0.2→0.3')
    expect(text).toContain('HELD1')
  })

  it('提案带 run_id 而文件取不回时点名"不见了"，且不编出逐例读数', async () => {
    const wrapper = await openDetail(withRun({ evolution_run: null, evolution_run_status: 'missing' }))
    const text = wrapper.text()
    expect(text).toContain('运行记录不见了')
    expect(text).not.toContain('留出侧逐例读数')
    expect(text).not.toContain('HELD0')
  })

  it('本轮未落运行记录时说成"未落记录"，不与"文件不见了"混成一句', async () => {
    const wrapper = await openDetail(withRun({ run_id: '', evolution_run: null, evolution_run_status: 'none_recorded' }))
    const text = wrapper.text()
    expect(text).toContain('本轮未落运行记录')
    expect(text).not.toContain('运行记录不见了')
  })

  it('判分不可用时明说本轮增益不可信', async () => {
    const wrapper = await openDetail(withRun({
      evolution_run: {
        ...withRun({}).evolution_run,
        judge_available: false,
      },
    }))
    expect(wrapper.text()).toContain('判分不可用')
  })
})

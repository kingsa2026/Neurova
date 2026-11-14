/**
 * AgentSkillPage — VideoEvolve 对照批（V1–V6）的前端适配读侧。
 *
 * 锁三件容易悄悄退让的事：
 *  1. 提案详情面必须把 V4 归因、V6 部署成本差、V3 可进化面与既有各门读数
 *     摆到审批人面前（后端有而前端不显示 = 证据白做）；
 *  2. V1 修复尝试逐轮审计（含「由修复通道救回」）在审计区可见；
 *  3. V5 可部署工件有列表/详情/回滚入口，回滚必须二次确认。
 * B3 递归分支账本：递归模式开启时走 evolve-recursive 并把分支账本摆出来。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { apiMock } = vi.hoisted(() => {
  const m: Record<string, any> = {
    getAgentSkills: vi.fn().mockResolvedValue([]),
    listConsolidationPlans: vi.fn().mockResolvedValue({ code: 0, data: [] }),
    searchAgentDomainHarnesses: vi.fn().mockResolvedValue({ data: [] }),
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
    evolveSkillRecursive: vi.fn(),
    pinSkill: vi.fn(),
    runLifecycleSweep: vi.fn(),
    updateEvolutionSettings: vi.fn(),
    abCompareSkills: vi.fn(),
    listArtifacts: vi.fn(),
    getArtifact: vi.fn(),
    rollbackArtifact: vi.fn(),
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
    domainHarnesses: '域级已采纳 harness', domainHarnessesHint: '跨域搜索已采纳 harness...',
  },
  skillEvo: {
    proposals: '待审提案', artifacts: '可部署工件', settings: '进化设置', runSweep: '扫描',
    pinned: '已钉住', pin: '钉住', unpin: '解钉', pinSuccess: 'ok', pinError: '失败',
    evolve: '进化', textEvolution: '文本进化', textEvolutionHint: 'h', lifecycleSweep: '扫描',
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
    abVerify: '双臂核验', abHint: 'h', abRunSimulated: '跑模拟面', abRunReal: '跑真轨迹面',
    abExecutor: '执行面', abKindSimulated: '模拟面', abKindReal: '真轨迹面',
    abMetricN: '任务数', abMetricBaseline: '基线', abMetricCandidate: '候选',
    abMetricDelta: '差', abTaskCol: '任务', abFailed: '核验失败',
    abKindMismatch: '执行面与所选不符', abNoCandidate: '无候选正文',
    auditRun: '进化审计运行', auditRunCases: '留出侧逐例读数',
    auditRunJudgeDown: '判分不可用', auditRunMissing: '运行记录不见了',
    auditRunNoneRecorded: '本轮未落运行记录',
    // ── 本批新增 ──
    attributionTitle: '增益归因', attrHoldoutGain: '留出增益', attrSizeDelta: '体积变化',
    attrRepairRounds: '修复轮数', attrRescued: '由修复通道救回', attrRegular: '常规胜出',
    deploymentCost: '部署成本差（每任务）', costUnmeasured: '未量到（{reason}）',
    costBaseline: '基线', costCandidate: '候选',
    surfaceTitle: '可进化面', artifactBudget: '尺寸预算',
    caseGateTitle: '例级不退化门', caseGateRegressions: '撞坏用例', caseGateUnevidenced: '未量出',
    caseGateAllowance: '容忍', execSuiteTitle: '可执行断言面通过率',
    judgeSealedTitle: 'judge×密封增益', judgeSealedCol: '密封', sourceMixTitle: '证据来源构成',
    costGateTitle: '成本门', modelUnderTest: '验收基座',
    repairAttemptsTitle: '修复尝试', repairImproved: '改善（tune {score}）',
    repairNotImproved: '未改善（tune {score}）', repairBlocked: '被{where}闸拦下',
    repairEvidence: '证据任务',
    artifactSurface: '可进化面', artifactChampion: '冠军正文', artifactVariants: '非劣变体（Pareto 多档）',
    artifactTier: '档位', artifactCostUsd: '成本（USD）', artifactTokens: 'Tokens',
    artifactEvidence: '证据指针', artifactRun: '运行', artifactProposal: '提案',
    artifactJournal: '日志仓', artifactBack: '返回列表', artifactRollback: '回滚',
    artifactRollbackConfirm: '确认回滚到基线正文？', artifactRollbackDone: '已回滚到基线正文',
    artifactListEmpty: '暂无可部署工件', artifactCreatedAt: '打包时间',
    recursiveMode: '递归模式', recursiveModeHint: 'h', recursiveEpochs: '递归轮数',
    recursivePoolSize: '候选池容量', recursiveBranchRetries: '分支重试额度',
    recursiveBranchRetriesHint: 'h', recursiveStopped: '停止原因',
    recursiveTotalImprovement: '总改善', recursiveBranches: '分支账本',
    branchId: '分支', branchParent: '母分支', branchEpoch: '入池轮', branchStatus: '状态',
    branchScore: '分数', recursiveDone: '递归演化完成：{epochs} 轮，总改善 {improvement}',
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

describe('AgentSkillPage — 提案详情的证据与代价读数（V3/V4/V6＋既有各门）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
    evolutionMock.getLifecycleUsage.mockResolvedValue({ data: { counts: {}, skills: [] } })
    evolutionMock.getEvolutionSettings.mockResolvedValue({ data: {} })
    evolutionMock.listProposals.mockResolvedValue({ data: [] })
  })

  const RICH = {
    ...PROPOSAL,
    model_under_test: 'qwen-test',
    gain_attribution: {
      surfaces_touched: ['instruction'], holdout_gain: 0.2, size_delta_ratio: 0.05,
      repair_rounds: 2, repair_rescued: true, note: 'n',
    },
    deployment_cost: {
      state: 'measured', baseline_per_case_usd: 0.01, candidate_per_case_usd: 0.02,
      delta_per_case_usd: 0.01, delta_ratio: 1.0,
      baseline_per_case_tokens: 100, candidate_per_case_tokens: 200,
      delta_per_case_tokens: 100, baseline_cop_usd: 0.011, candidate_cop_usd: 0.022,
    },
    surface: { name: 'template', label: '提示模板', kind: 'text', max_size: 15000 },
    case_gate: { allowance: 1, regressions: ['c'], unevidenced: [] },
    exec_suite: { state: 'measured', baseline_pass_rate: 1.0, candidate_pass_rate: 0.75 },
    judge_vs_sealed: { judge_gain: 0.2, sealed_gain: 0.15, missing: [] },
    source_mix: { golden: 3, synthetic: 2 },
    cost_gate: { state: 'manual_review', ratio: 0.4, threshold: 0.2 },
  }

  it('归因/成本差/面/各门读数全部上屏，且修复救回如实标注', async () => {
    const wrapper = await openDetail(RICH)
    const text = wrapper.text()
    expect(text).toContain('增益归因')
    expect(text).toContain('留出增益 +0.2')
    expect(text).toContain('体积变化 5.0%')
    expect(text).toContain('修复轮数 2')
    expect(text).toContain('由修复通道救回')
    expect(text).toContain('部署成本差（每任务）')
    expect(text).toContain('基线 $0.01 → 候选 $0.02')
    expect(text).toContain('CoP $0.011→$0.022')
    expect(text).toContain('提示模板 (template)')
    expect(text).toContain('例级不退化门')
    expect(text).toContain('撞坏用例 1')
    expect(text).toContain('可执行断言面通过率')
    expect(text).toContain('100% → 75%')
    expect(text).toContain('judge×密封增益')
    expect(text).toContain('密封 +0.15')
    expect(text).toContain('证据来源构成')
    expect(text).toContain('golden 3')
    expect(text).toContain('成本门')
    expect(text).toContain('manual_review')
    expect(text).toContain('验收基座')
    expect(text).toContain('qwen-test')
  })

  it('审计里的修复尝试逐轮可见（门别/改善/证据任务）', async () => {
    const wrapper = await openDetail({
      ...RICH,
      evolution_run: {
        run_id: 'run_1', at: '', skill_id: 's1', artifact_type: 'skill',
        iterations_run: 1, holdout_before: 0.4, holdout_after: 0.6,
        judge_available: true, holdout_cases: {},
        repair_rescued: true,
        repair_attempts: [
          { round: 1, gate: 'case_regression', improved: true, tune_score: 0.72,
            evidence_tasks: ['c'] },
          { round: 2, gate: 'holdout_regression', improved: false, tune_score: 0.7,
            blocked: 'constraints', evidence_tasks: [] },
        ],
      },
      evolution_run_status: 'attached',
    })
    const text = wrapper.text()
    expect(text).toContain('修复尝试')
    expect(text).toContain('#1 case_regression')
    expect(text).toContain('改善（tune 0.72）')
    expect(text).toContain('证据任务')
    expect(text).toContain('#2 holdout_regression')
    expect(text).toContain('被constraints闸拦下')
  })

  it('旧记录没有新读数键时不渲染空面板', async () => {
    const wrapper = await openDetail(PROPOSAL)
    const text = wrapper.text()
    expect(text).not.toContain('增益归因')
    expect(text).not.toContain('部署成本差（每任务）')
    expect(text).not.toContain('修复尝试')
  })

  it('成本差未量到时诚实显示原因，不冒充 0', async () => {
    const wrapper = await openDetail({
      ...RICH,
      deployment_cost: { state: 'unmeasured', reason: 'no_usage_events' },
    })
    expect(wrapper.text()).toContain('未量到（no_usage_events）')
  })
})

describe('AgentSkillPage — V5 可部署工件面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
    evolutionMock.getLifecycleUsage.mockResolvedValue({ data: { counts: {}, skills: [] } })
    evolutionMock.getEvolutionSettings.mockResolvedValue({ data: {} })
    evolutionMock.listProposals.mockResolvedValue({ data: [] })
  })

  const ARTIFACT = {
    artifact_id: 'art_1', skill_id: 's1', artifact_type: 'skill',
    status: 'applied', created_at: '2026-11-15T00:00:00+00:00',
    champion_text: '冠军正文', baseline_text: '基线正文',
    variants: [{ text: 'V1', score: 0.9, tier: 'lite', cost_usd: 0.1, tokens: 10 }],
    evidence: { run_id: 'run_1', proposal_id: 'evo_1', journal_commit: 'abc123' },
    scores: { holdout_after: 0.6 },
    surface: { name: 'template', label: '提示模板', kind: 'text', max_size: 15000 },
  }

  it('工件列表按 agent 拉取并展示状态', async () => {
    evolutionMock.listArtifacts.mockResolvedValue({ code: 0, data: [ARTIFACT] })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArtifacts()
    await flushPromises()
    expect(evolutionMock.listArtifacts).toHaveBeenCalledWith('agent-1')
    const text = wrapper.text()
    expect(text).toContain('art_1')
    expect(text).toContain('applied')
  })

  it('工件详情展示冠军/变体/证据指针；查看动作本身不触发回滚', async () => {
    evolutionMock.listArtifacts.mockResolvedValue({ code: 0, data: [ARTIFACT] })
    evolutionMock.getArtifact.mockResolvedValue({ code: 0, data: ARTIFACT })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArtifacts()
    await flushPromises()
    await (wrapper.vm as any).viewArtifact(ARTIFACT)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('冠军正文')
    expect(text).toContain('非劣变体（Pareto 多档）')
    expect(text).toContain('lite')
    expect(text).toContain('abc123')
    // 查看详情只是看：回滚端点不得被顺带触发
    expect(evolutionMock.rollbackArtifact).not.toHaveBeenCalled()
  })

  it('回滚确认后调用端点并刷新列表；后端拒滚时原样报错', async () => {
    evolutionMock.listArtifacts.mockResolvedValue({ code: 0, data: [ARTIFACT] })
    evolutionMock.getArtifact.mockResolvedValue({ code: 0, data: ARTIFACT })
    evolutionMock.rollbackArtifact.mockResolvedValue({ code: 0, data: { rolled_back: true } })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArtifacts()
    await flushPromises()
    // 进入详情并把确认钮点亮
    await (wrapper.vm as any).viewArtifact(ARTIFACT)
    await flushPromises()
    const vm = wrapper.vm as any
    vm.rollbackConfirmId = ARTIFACT.artifact_id
    await vm.doRollbackArtifact(ARTIFACT)
    await flushPromises()
    expect(evolutionMock.rollbackArtifact).toHaveBeenCalledWith('agent-1', 'art_1')

    evolutionMock.rollbackArtifact.mockRejectedValue({
      response: { data: { detail: '技能正文已偏离工件冠军形态（批准后被改过），拒绝覆盖；请先核对当前正文' } },
    })
    await vm.doRollbackArtifact(ARTIFACT)
    await flushPromises()
    // 后端拒滚的 detail 原样上屏（message.error），不吞成泛化的"失败"
    const { message } = await import('ant-design-vue')
    const calls = (message.error as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
    expect(calls.some((m) => m.includes('拒绝覆盖'))).toBe(true)
  })
})

describe('AgentSkillPage — V2 递归演化的分支账本', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
    evolutionMock.getLifecycleUsage.mockResolvedValue({ data: { counts: {}, skills: [] } })
    evolutionMock.getEvolutionSettings.mockResolvedValue({ data: {} })
    evolutionMock.listProposals.mockResolvedValue({ data: [] })
  })

  it('递归模式走 evolve-recursive，分支账本上屏', async () => {
    evolutionMock.evolveSkillRecursive.mockResolvedValue({
      code: 0,
      data: {
        skill_id: 's1', baseline_text: 'B', deployed_text: 'B+I',
        epochs_run: 2, epochs: [], pool_size: 2, branch_retries: 1,
        branches: [
          { branch_id: 'br1', parent_id: '', epoch_created: 0, status: 'promoted',
            retries_left: 0, score: 0.6, promoted_epoch: 1, text_head: 'B' },
          { branch_id: 'br2', parent_id: 'br1', epoch_created: 1, status: 'active',
            retries_left: 1, score: 0.7, promoted_epoch: null, text_head: 'B I' },
        ],
        seed_branch_id: 'br1', final_pool_size: 1,
        total_improvement: 0.1, stopped_reason: 'epochs_exhausted',
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.openEvolve({ id: 's1', name: 'S1' })
    vm.evolveRecursiveMode = true
    await vm.runEvolve()
    await flushPromises()

    expect(evolutionMock.evolveSkillRecursive).toHaveBeenCalledWith('agent-1', {
      skill_id: 's1', epochs: 2, pool_size: 1, branch_retries: 0,
      iterations: 5, dataset_source: 'auto',
    })
    const text = wrapper.text()
    expect(text).toContain('分支账本')
    expect(text).toContain('br1')
    expect(text).toContain('promoted')
    expect(text).toContain('epochs_exhausted')
    // 单臂端点不得被误调
    expect(evolutionMock.evolveSkill).not.toHaveBeenCalled()
  })
})

/**
 * AgentSkillPage — 技能合并审批入口（P1-2 前端接线）
 *
 * 背景：后端三端点（GET plans / POST approve / POST reject）已落地并已鉴权，
 * 但 NeurUI 侧零引用 —— "后端有了没人调"是同一种接线断裂的反向形态。
 * 本文件锁定前端入口的契约：
 *  - 工具栏渲染「技能合并」入口；
 *  - 打开即拉 GET /skill-pool/agent/{id}/consolidation/plans；
 *  - 只展示待审件（落盘仓含已批/已拒历史条目，不能冒充待办）；
 *  - 计划卡显示聚簇依据（identity/structure/name_prefix）与吸收成员；
 *  - 批准/拒绝分别调 approve/reject，并刷新列表与技能网格；
 *  - 空计划渲染 empty 文案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { apiMock } = vi.hoisted(() => {
  const apiMock: Record<string, any> = {
    getAgentSkills: vi.fn().mockResolvedValue([]),
    listConsolidationPlans: vi.fn().mockResolvedValue([]),
    approveConsolidation: vi.fn().mockResolvedValue({ code: 0 }),
    rejectConsolidation: vi.fn().mockResolvedValue({ code: 0 }),
  }
  return { apiMock }
})

vi.mock('@/api/modules/skill-pool', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(apiMock).map((k) => [k, (...a: unknown[]) => apiMock[k](...a)])),
}))

const { evolutionMock } = vi.hoisted(() => {
  const evolutionMock: Record<string, any> = {
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
  }
  return { evolutionMock }
})
vi.mock('@/api/modules/text-evolution', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(evolutionMock).map((k) => [k, (...a: unknown[]) => evolutionMock[k](...a)])),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import AgentSkillPage from '../AgentSkillPage.vue'

const PLAN = {
  umbrella: 'file_read_file_write_skill',
  absorbed: ['genetic_file_read_file_write', 'synth_deadbeef'],
  reason: '业务身份重复：3 个条目工具序列+意图全同，收敛为类级技能',
  basis: 'identity',
  structure: 'file_read → file_write',
  status: 'pending',
}

const messages = {
  common: { refresh: '刷新', save: '保存', cancel: '取消' },
  skill: {
    totalSkills: '技能总数', enabledSkills: '已启用技能', executionCount: '执行次数',
    searchPlaceholder: '搜索技能', enabled: '已启用', disabled: '已禁用', executions: '执行次数',
    execute: '执行', noSkills: '暂无技能', loadError: '加载失败', installSuccess: '已安装',
    importFromMarket: '从市场导入', noMarketSkills: '暂无可导入的公共技能',
    executeSkill: '执行技能', arguments: '参数', argsPlaceholder: '输入 JSON 参数',
    executeSuccess: '执行成功', executeError: '执行失败', install: '安装',
    enabledSuccess: '已启用', disabledSuccess: '已禁用', toggleError: '切换状态失败',
    pushToMine: '推送到我的库', pushSubmitted: '推送已提交', pushError: '推送失败',
    marketSearchPlaceholder: '搜索技能',
  },
  skillEvo: {
    proposals: '待审提案', settings: '进化设置', runSweep: '立即扫描', pinned: '已钉住',
    pin: '钉住', unpin: '解钉', pinSuccess: '已更新', pinError: '钉住失败', evolve: '进化',
    textEvolution: '文本进化', textEvolutionHint: 'h', lifecycleSweep: '生命周期扫描',
    lifecycleSweepHint: 'h', sweepInterval: '间隔', saveSuccess: '已保存', saveError: '保存失败',
    runEvolve: '开始进化', iterations: '迭代轮数', datasetSource: '评测集来源', sourceAuto: '自动',
    sourceGolden: '手写', sourceMined: '挖掘', sourceSynthetic: '合成', evolveError: '进化失败',
    accepted: '已通过', noChange: '无变化', noProposals: '暂无待审提案', view: '查看',
    approve: '批准', reject: '拒绝', approved: '已批准', rejectedOk: '已拒绝', decideError: '审批失败',
    proposalDetail: '提案详情', holdout: '留出集', iterationsUnit: '轮', baseline: '改进前',
    improved: '改进后', loadError: '加载失败', stateActive: '活跃', stateStale: '陈旧',
    stateArchived: '已归档', agentCreated: '智能体创建',
    consolidation: '技能合并', consolidationHint: '合并说明', consolidationEmpty: '暂无待审合并计划',
    consolidationAbsorbed: '吸收成员', consolidationApprove: '批准合并',
    consolidationApproved: '已批准', consolidationRejected: '已拒绝', consolidationError: '合并失败',
    consolidationBasisIdentity: '同身份重复', consolidationBasisStructure: '同序列跨意图',
    consolidationBasisNamePrefix: '名字前缀兜底',
    archive: '归档', archiveTitle: '归档与回滚', archiveEmpty: '暂无可回滚的归档',
    archiveVersion: '版本', archiveArchivedAt: '归档时间', rollback: '回滚',
    rollbackConfirm: '确认回滚？', rollbackDone: '已回滚，剩余归档 {left} 份',
    rollbackError: '回滚失败', archiveLoadError: '归档加载失败',
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
        GlassCard: {
          props: ['title', 'subtitle'],
          template: '<div class="gc"><h3>{{ title }}</h3><span>{{ subtitle }}</span><slot /></div>',
        },
        GlassButton: {
          props: ['variant', 'size', 'loading', 'disabled'],
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot /></button>',
        },
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

describe('AgentSkillPage — 技能合并审批入口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([])
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [] })
  })

  it('工具栏渲染「技能合并」入口', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('技能合并')
  })

  it('打开入口拉取 plans 并按 agentId 定库', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.openConsolidation()
    expect(apiMock.listConsolidationPlans).toHaveBeenCalledWith('agent-1')
  })

  it('只展示待审件（已批/已拒历史条目不得冒充待办）', async () => {
    apiMock.listConsolidationPlans.mockResolvedValue({
      code: 0,
      data: [PLAN, { ...PLAN, umbrella: 'done_one', status: 'approved' }],
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.refreshConsolidation()
    expect(vm.consolidationPlans.map((p: any) => p.umbrella)).toEqual([PLAN.umbrella])
    expect(wrapper.text()).not.toContain('done_one')
  })

  it('计划卡显示聚簇依据与吸收成员', async () => {
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [PLAN] })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.refreshConsolidation()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(PLAN.umbrella)
    expect(text).toContain('同身份重复')
    expect(text).toContain('genetic_file_read_file_write')
    expect(text).toContain('吸收成员')
  })

  it('批准调 approveConsolidation 并刷新列表 + 技能网格', async () => {
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [PLAN] })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.refreshConsolidation()
    const skillsBefore = apiMock.getAgentSkills.mock.calls.length
    await vm.decideConsolidation(PLAN, true)
    expect(apiMock.approveConsolidation).toHaveBeenCalledWith('agent-1', PLAN.umbrella)
    expect(apiMock.listConsolidationPlans.mock.calls.length).toBeGreaterThan(1)
    expect(apiMock.getAgentSkills.mock.calls.length).toBeGreaterThan(skillsBefore)
  })

  it('拒绝调 rejectConsolidation（库零改动路径）', async () => {
    apiMock.listConsolidationPlans.mockResolvedValue({ code: 0, data: [PLAN] })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.decideConsolidation(PLAN, false)
    expect(apiMock.rejectConsolidation).toHaveBeenCalledWith('agent-1', PLAN.umbrella)
  })

  it('无计划时渲染 empty 文案', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.refreshConsolidation()
    await flushPromises()
    expect(apiMock.listConsolidationPlans).toHaveBeenCalled()
    expect(wrapper.text()).toContain('暂无待审合并计划')
  })
})

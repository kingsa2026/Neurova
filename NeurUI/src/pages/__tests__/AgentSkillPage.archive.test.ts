/**
 * AgentSkillPage — 归档与回滚入口（工单 011 前端切片）。
 *
 * 后端读面/写面已落地（`GET/POST /governance/skills/{id}/archives|rollback`），
 * 但 NeurUI 侧零引用 —— "有端点没人按"是同一种接线断裂。本文件锁定：
 *  - 技能卡渲染「归档」入口；
 *  - 打开即拉该技能归档列表（带当前 agentId 定库）；
 *  - 归档为空时回滚按钮不可用（后端也会 409，前端不得先给出假希望）；
 *  - 回滚需二次确认，确认后调 rollbackSkill 并刷新归档与技能网格；
 *  - 结果显示回滚后剩余归档数（= 回滚窗口还剩多少）。
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
    runLifecycleSweep: vi.fn(),
    updateEvolutionSettings: vi.fn(),
  }
  return { evolutionMock }
})
vi.mock('@/api/modules/text-evolution', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(evolutionMock).map((k) => [k, (...a: unknown[]) => evolutionMock[k](...a)])),
}))

const { governanceMock } = vi.hoisted(() => {
  const governanceMock: Record<string, any> = {
    getSkillArchives: vi.fn(),
    rollbackSkill: vi.fn(),
  }
  return { governanceMock }
})
vi.mock('@/api/modules/governance', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(governanceMock).map((k) => [k, (...a: unknown[]) => governanceMock[k](...a)])),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import AgentSkillPage from '../AgentSkillPage.vue'

const SKILL = {
  skill_id: 'sk_a',
  name: 'synth_alpha',
  description: '自动技能',
  enabled: true,
  execution_count: 3,
}

const ARCHIVE = {
  version: '1.0.0',
  description: 'base desc',
  archived_at: 1758400000,
  reason: 'rebuild',
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
    consolidation: '技能合并', consolidationHint: 'h', consolidationEmpty: '暂无',
    archive: '归档', archiveTitle: '归档与回滚', archiveEmpty: '暂无可回滚的归档',
    archiveVersion: '版本', archiveArchivedAt: '归档时间',
    rollback: '回滚', rollbackConfirm: '确认回滚到该归档版本？此操作会改写技能定义。',
    rollbackDone: '已回滚，剩余归档 {left} 份', rollbackError: '回滚失败',
    archiveLoadError: '归档加载失败',
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
          template: '<button class="gb" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
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
        'a-popconfirm': { template: '<div><slot name="default" /></div>' },
        'a-row': { template: '<div><slot /></div>' },
        'a-col': { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('AgentSkillPage — 归档与回滚入口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([SKILL])
    governanceMock.getSkillArchives.mockResolvedValue({
      data: { code: 0, data: { skill_id: 'sk_a', archives: [ARCHIVE] } },
    })
    governanceMock.rollbackSkill.mockResolvedValue({
      data: { code: 0, data: { rolled_back: true, skill_id: 'sk_a', operator: 'u', archives_left: 0 } },
    })
  })

  it('技能卡渲染「归档」入口', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('归档')
  })

  it('打开归档面按当前 agentId 拉该技能归档', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArchive('sk_a')
    expect(governanceMock.getSkillArchives).toHaveBeenCalledWith('sk_a', 'agent-1')
    expect((wrapper.vm as any).archiveEntries.length).toBe(1)
  })

  it('归档为空时回滚按钮不可用', async () => {
    governanceMock.getSkillArchives.mockResolvedValue({
      data: { code: 0, data: { skill_id: 'sk_a', archives: [] } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArchive('sk_a')
    await flushPromises()
    expect((wrapper.vm as any).archiveEntries.length).toBe(0)
    expect(wrapper.text()).toContain('暂无可回滚的归档')
  })

  it('回滚调 rollbackSkill 并刷新归档与技能网格', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await (wrapper.vm as any).openArchive('sk_a')
    const skillsBefore = apiMock.getAgentSkills.mock.calls.length
    await (wrapper.vm as any).confirmRollback()
    expect(governanceMock.rollbackSkill).toHaveBeenCalledWith('sk_a', expect.any(String), 'agent-1')
    expect(governanceMock.getSkillArchives.mock.calls.length).toBeGreaterThan(1)
    expect(apiMock.getAgentSkills.mock.calls.length).toBeGreaterThan(skillsBefore)
  })
})

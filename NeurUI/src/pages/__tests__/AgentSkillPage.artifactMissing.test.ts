/**
 * AgentSkillPage — 「已启用」不等于「能跑」（§6-272 读面对账的前端那一腿）。
 *
 * 后端把每条账目的对账读数投影成 `available` / `unavailable_reason`（单点在
 * `SkillService.availabilityFor`）。本文件锁三件事：
 *  1. 账本在册而构件缺失的技能，卡上出现「构件缺失·不可用」标；
 *  2. 健康技能卡上**没有**这个标（不许把判定渲染成常驻噪声）；
 *  3. 原因文本走 `title` 透出，前端不自己拼一套解释（两处判因迟早分叉）。
 *
 * 断言按**卡片节点**取而不是整页 `text()`：本页工具条/统计条也有"已启用技能"这类字样，
 * 整页包含断言会被别处满足而恒绿（本仓记过的前端常驻假绿同族）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { apiMock } = vi.hoisted(() => {
  const apiMock: Record<string, any> = {
    getAgentSkills: vi.fn().mockResolvedValue([]),
    listConsolidationPlans: vi.fn().mockResolvedValue([]),
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
    getSkillArchives: vi.fn().mockResolvedValue({ data: { code: 0, data: { archives: [] } } }),
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

const ARTIFACT_TAG = '构件缺失·不可用'
const REASON = '落盘无可执行构件（既无 SKILL.md 指令体，也无入口脚本）'

const SHELL = {
  id: 'sk_shell', skill_id: 'sk_shell', name: 'shell_only_entry', description: '只有记账件',
  enabled: true, available: false, unavailable_reason: REASON,
}
const HEALTHY = {
  id: 'sk_ok', skill_id: 'sk_ok', name: 'doc_shape_entry', description: '有指令体',
  enabled: true, available: true, unavailable_reason: '',
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
    marketSearchPlaceholder: '搜索技能', artifactMissing: ARTIFACT_TAG,
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
        'a-tag': { props: ['color', 'title'], template: '<span class="tag" :title="title"><slot /></span>' },
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

function cardOf(wrapper: any, skillName: string) {
  // 技能名由卡壳的标题渲染（`GlassCard :title`），卡体里没有 ⇒ 按卡壳取再按标题认人
  const cards = wrapper.findAll('.gc')
  const hit = cards.filter((c: any) => c.find('h3').text() === skillName)
  expect(hit.length, `找不到技能卡：${skillName}（现有标题：${cards.map((c: any) => c.find('h3').text()).join(', ')}）`).toBe(1)
  return hit[0]
}

describe('AgentSkillPage — 构件缺失如实标注', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.getAgentSkills.mockResolvedValue([SHELL, HEALTHY])
  })

  it('空壳卡上有「构件缺失·不可用」标，健康卡上没有', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(cardOf(wrapper, 'shell_only_entry').findAll('.tag').some((t: any) => t.text() === ARTIFACT_TAG)).toBe(true)
    expect(cardOf(wrapper, 'doc_shape_entry').findAll('.tag').some((t: any) => t.text() === ARTIFACT_TAG)).toBe(false)
  })

  it('原因文本按后端读数透出，前端不自己拼一份解释', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const tag = cardOf(wrapper, 'shell_only_entry').findAll('.tag').find((t: any) => t.text() === ARTIFACT_TAG)
    expect(tag?.attributes('title')).toBe(REASON)
  })

  it('「已启用」标与「构件缺失」标各说各事，同卡并存不互相顶替', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const texts = cardOf(wrapper, 'shell_only_entry').findAll('.tag').map((t: any) => t.text())
    expect(texts).toContain('已启用')
    expect(texts).toContain(ARTIFACT_TAG)
  })
})

/**
 * 3.6-1 审计收口（R5）：
 * - 待审产物审批面接线：activeTab 'pending' 此前无 tab-pane，fetchPending 与
 *   批/拒按钮整块不可达（审计 SkillPoolPage.vue:209,256-316）；本档钉「待审」
 *   tab 渲染、切页拉取、批/拒调用。
 * - 技能代码输入框退役：后端 SkillCreate/SkillUpdate 契约无 code 字段（技能
 *   执行体两条腿——映射表/落盘入口 .py——都不吃它），表单收集即丢弃属假成功
 *   面；本档钉创建弹窗不再渲染该输入框。后端支持 code 落盘后再恢复。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock } = vi.hoisted(() => {
  const apiMock: Record<string, any> = {
    listPublicLibrarySkills: vi.fn().mockResolvedValue([]),
    listMySkills: vi.fn().mockResolvedValue([]),
    listSkillTransfers: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
    acceptSkillTransfer: vi.fn().mockResolvedValue({ code: 0 }),
    rejectSkillTransfer: vi.fn().mockResolvedValue({ code: 0 }),
    listPendingSkills: vi.fn().mockResolvedValue({ data: [] }),
    listPendingExperiences: vi.fn().mockResolvedValue({ data: [] }),
    approvePendingSkill: vi.fn().mockResolvedValue({ code: 0 }),
    rejectPendingSkill: vi.fn().mockResolvedValue({ code: 0 }),
    approvePendingExperience: vi.fn().mockResolvedValue({ code: 0 }),
    rejectPendingExperience: vi.fn().mockResolvedValue({ code: 0 }),
    installPublicToMine: vi.fn().mockResolvedValue({ code: 0 }),
    createMySkill: vi.fn().mockResolvedValue({ skill_id: 'c1' }),
    updateMySkill: vi.fn().mockResolvedValue({}),
    deleteMySkill: vi.fn().mockResolvedValue({ code: 0 }),
    installSkillFromUrl: vi.fn(),
    installSkillFromZip: vi.fn(),
    submitSkillForReview: vi.fn().mockResolvedValue({ code: 0 }),
  }
  return { apiMock }
})

vi.mock('@/api/modules/skill-pool', () => ({
  __esModule: true,
  ...Object.fromEntries(Object.keys(apiMock).map((k) => [k, (...a: unknown[]) => apiMock[k](...a)])),
}))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn() } }))

import SkillPoolPage from '../SkillPoolPage.vue'

const messages: Record<string, any> = {
  zhCN: {
    common: { required: 'r', save: 's', delete: 'd', close: 'c', create: 'c', edit: 'e', search: 'q', loading: 'l' },
    skillPool: {
      title: '技能池', publicSkills: '公共技能', privateSkills: '我的技能', transferTab: '流转确认',
      pendingReview: '待审', pendingSkills: '待审技能', pendingExperiences: '待审经验',
      approve: '批准', reject: '拒绝', noPending: '暂无待审产物',
      transfersHint: 'h', noTransfers: '暂无待确认流转',
      transferAccept: '确认', transferReject: '拒绝',
      transferKindUpgrade: '升级', transferKindInitial: '初推', transferFrom: '源：',
      transferAccepted: '已确认', transferRejected: '已拒绝', transferError: '出错',
      noPublic: 'n', noPrivate: 'n', searchPublic: 'q', searchPrivate: 'q',
      install: 'i', installSuccess: 'ok', installError: 'e', loadError: 'e',
      general: 'g', createSkill: 'c', editSkill: 'e', skillName: 'n', skillDesc: 'd',
      skillCategory: 'c', namePlaceholder: 'p', descPlaceholder: 'p',
      categoryPlaceholder: 'p', updateSuccess: 'u', uploading: 'u', zipInvalid: 'z',
      publishToPublic: 'pub', publishSubmitted: 'sub', publishError: 'perr',
      createSuccess: 'cs', saveError: 'se', confirmDelete: 'cd', deleteSuccess: 'ds', deleteError: 'de',
      private: '私有',
      urlInputTitle: 'u', urlInputDesc: 'ud', urlInputPlaceholder: 'up',
      installFromUrl: 'iu', importZip: 'iz',
    },
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zhCN', messages })
  setActivePinia(createPinia())
  return mount(SkillPoolPage, { global: { plugins: [i18n], stubs: {
    GlassCard: { props: ['title', 'subtitle'], template: '<div class="gc"><h3>{{ title }}</h3><span>{{ subtitle }}</span><slot /><slot name="footer" /></div>' },
    GlassButton: { props: ['variant', 'size', 'loading', 'disabled'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
    UiIcon: { template: '<i />' },
    'a-tabs': { template: '<div><slot /></div>' },
    'a-tab-pane': { props: ['tab'], template: '<div><span class="tab-label">{{ tab }}</span><slot /></div>' },
    'a-input-search': { props: ['value'], template: '<input />' },
    'a-spin': { props: ['spinning'], template: '<div><slot /></div>' },
    'a-empty': { props: ['description'], template: '<div class="empty">{{ description }}</div>' },
    'a-tag': { template: '<span class="tag"><slot /></span>' },
    'a-pagination': { template: '<div />' },
    'a-modal': { props: ['title'], template: '<div class="modal"><slot /></div>' },
    'a-form': { template: '<div><slot /></div>' },
    'a-form-item': { props: ['label'], template: '<div class="form-item">{{ label }}<slot /></div>' },
    'a-input': { props: ['value'], template: '<input />' },
    'a-textarea': { props: ['value'], template: '<textarea />' },
    'a-button': { template: '<button><slot /></button>' },
  } } })
}

async function openPendingTab(wrapper: ReturnType<typeof mountPage>) {
  const vm = wrapper.vm as any
  vm.activeTab = 'pending'
  await flushPromises()
}

describe('SkillPoolPage — 3.6-1 待审产物审批面接线', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listPublicLibrarySkills.mockResolvedValue([])
    apiMock.listMySkills.mockResolvedValue([])
    apiMock.listSkillTransfers.mockResolvedValue({ data: { items: [], total: 0 } })
    apiMock.listPendingSkills.mockResolvedValue({ data: [] })
    apiMock.listPendingExperiences.mockResolvedValue({ data: [] })
  })

  it('「待审」tab 可达：页面上渲染 pendingReview tab 标签（旧实现无 pane 不可达）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const labels = wrapper.findAll('.tab-label').map((n) => n.text())
    expect(labels).toContain('待审')
  })

  it('切到待审 tab 拉取待审技能与经验并渲染空态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await openPendingTab(wrapper)
    expect(apiMock.listPendingSkills).toHaveBeenCalledWith('_all')
    expect(apiMock.listPendingExperiences).toHaveBeenCalledWith('_all')
    expect(wrapper.text()).toContain('待审技能')
    expect(wrapper.text()).toContain('待审经验')
    expect(wrapper.text()).toContain('暂无待审产物')
  })

  it('待审技能行渲染并驱动批/拒调用', async () => {
    apiMock.listPendingSkills.mockResolvedValue({
      data: [{ template_id: 'tpl-1', name: '自动技能A', description: '工具序列产物' }],
    })
    const wrapper = mountPage()
    await flushPromises()
    await openPendingTab(wrapper)
    expect(wrapper.text()).toContain('自动技能A')
    const vm = wrapper.vm as any
    await vm.handleApproveSkill('tpl-1')
    expect(apiMock.approvePendingSkill).toHaveBeenCalledWith('_all', 'tpl-1')
    await vm.handleRejectSkill('tpl-1')
    expect(apiMock.rejectPendingSkill).toHaveBeenCalledWith('_all', 'tpl-1')
  })

  it('待审经验行渲染并驱动批/拒调用', async () => {
    apiMock.listPendingExperiences.mockResolvedValue({
      data: [{ record_id: 'rec-1', skill_id: 's1', source: 'auto', content: '经验内容X' }],
    })
    const wrapper = mountPage()
    await flushPromises()
    await openPendingTab(wrapper)
    expect(wrapper.text()).toContain('经验内容X')
    const vm = wrapper.vm as any
    await vm.handleApproveExperience('rec-1')
    expect(apiMock.approvePendingExperience).toHaveBeenCalledWith('_all', 'rec-1')
    await vm.handleRejectExperience('rec-1')
    expect(apiMock.rejectPendingExperience).toHaveBeenCalledWith('_all', 'rec-1')
  })

  it('创建弹窗不再渲染「技能代码」输入框（后端契约无 code 字段，收集即丢弃）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.openCreateModal()
    await flushPromises()
    const labels = wrapper.findAll('.form-item').map((n) => n.text())
    expect(labels.join('|')).not.toContain('code')
    expect((wrapper.element as HTMLElement).querySelectorAll('textarea').length).toBeLessThanOrEqual(1)
  })
})

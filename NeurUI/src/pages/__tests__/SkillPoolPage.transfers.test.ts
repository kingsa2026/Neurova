/**
 * SettingPage — 技能召回与进化卡扩为五开关（Wave H-W5 后续追加 tool_search/语义两开关）
 * SkillPoolPage — 三层库流转确认队列 tab
 *
 * 验收（本文件）：
 * - SkillPoolPage 渲染「流转确认」tab；fetchTransfers 回填列表；
 * - accept 调 acceptSkillTransfer(id) 成功后刷新队列；reject 同理；
 * - 空队列渲染 empty 文案。
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
    createSkillTransfer: vi.fn().mockResolvedValue({ code: 0 }),
    installPublicToMine: vi.fn().mockResolvedValue({ code: 0 }),
    createMySkill: vi.fn().mockResolvedValue({ skill_id: 'c1' }),
    updateMySkill: vi.fn().mockResolvedValue({}),
    deleteMySkill: vi.fn().mockResolvedValue({ code: 0 }),
    listPendingSkills: vi.fn().mockResolvedValue({ data: [] }),
    listPendingExperiences: vi.fn().mockResolvedValue({ data: [] }),
    approvePendingSkill: vi.fn(),
    rejectPendingSkill: vi.fn(),
    approvePendingExperience: vi.fn(),
    rejectPendingExperience: vi.fn(),
    installSkillFromUrl: vi.fn(),
    installSkillFromZip: vi.fn(),
    executeSkill: vi.fn(),
    enableSkill: vi.fn(),
    submitSkillForReview: vi.fn().mockResolvedValue({ code: 0 }),
    listSkillSubmissions: vi.fn().mockResolvedValue({ data: { items: [] } }),
    reviewSkillSubmission: vi.fn(),
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
      publicSkills: '公共技能', privateSkills: '我的技能', transferTab: '流转确认',
      transfersHint: '队列说明文案', noTransfers: '暂无待确认流转',
      transferAccept: '确认', transferReject: '拒绝',
      transferKindUpgrade: '升级', transferKindInitial: '初推', transferFrom: '源：',
      transferAccepted: '已确认', transferRejected: '已拒绝', transferError: '出错',
      noPublic: 'n', noPrivate: 'n', searchPublic: 'q', searchPrivate: 'q',
      install: 'i', installSuccess: 'ok', installError: 'e', loadError: 'e',
      general: 'g', createSkill: 'c', editSkill: 'e', skillName: 'n', skillDesc: 'd',
      skillCategory: 'c', skillCode: 'c', namePlaceholder: 'p', descPlaceholder: 'p',
      categoryPlaceholder: 'p', updateSuccess: 'u', shareSuccess: 'x', unshareSuccess: 'x',
      shareError: 'x', pushSuccess: 'p', pushError: 'p', uploading: 'u', zipInvalid: 'z',
      publishToPublic: '发布到公共库', publishSubmitted: '已提交审批', publishError: '提交失败',
      createSuccess: 'cs', saveError: 'se', confirmDelete: 'cd', deleteSuccess: 'ds', deleteError: 'de',
      private: '私有',
      urlInputTitle: 'u', pendingTab: '待审', pendingHint: 'h', approve: 'a', reject: 'r',
      pendingSkillsTitle: 'ps', pendingExperiencesTitle: 'pe', noPending: 'np',
      importFromUrl: 'iu', importFromZip: 'iz',
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
    'a-spin': { template: '<div><slot /></div>' },
    'a-empty': { props: ['description'], template: '<div class="empty">{{ description }}</div>' },
    'a-tag': { template: '<span class="tag"><slot /></span>' },
    'a-pagination': { template: '<div />' },
    'a-modal': { template: '<div><slot /></div>' },
    'a-form': { template: '<div><slot /></div>' },
    'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
    'a-input': { props: ['value'], template: '<input />' },
    'a-textarea': { props: ['value'], template: '<textarea />' },
    'a-button': { template: '<button><slot /></button>' },
    'a-upload': { template: '<div><slot /></div>' },
  } } })
}

describe('SkillPoolPage — 流转确认队列（Wave H-W5）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listPublicLibrarySkills.mockResolvedValue([])
    apiMock.listMySkills.mockResolvedValue([])
    apiMock.listSkillTransfers.mockResolvedValue({ data: { items: [], total: 0 } })
  })

  it('私有 tab 读用户私库并归一 skill_id→id（裸数组契约，非 res.data）', async () => {
    apiMock.listMySkills.mockResolvedValue([
      { skill_id: 'm1', name: '我的技能', description: 'd', version: '1.0.0', category: 'c' },
    ])
    const wrapper = mountPage()
    await flushPromises()
    expect(apiMock.listMySkills).toHaveBeenCalled()
    const vm = wrapper.vm as any
    expect(vm.privateSkills[0].id).toBe('m1')
    expect(wrapper.text()).toContain('我的技能')
  })

  it('公共 tab 安装走 installPublicToMine（落我的私库）', async () => {
    apiMock.listPublicLibrarySkills.mockResolvedValue([
      { skill_id: 'p1', name: '公共技能', description: 'd', version: '1.0.0' },
    ])
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.installPublic({ id: 'p1', name: '公共技能', description: 'd' })
    expect(apiMock.installPublicToMine).toHaveBeenCalledWith('p1')
  })

  it('私有技能发布到公共库走 submitSkillForReview（管理员审批通道）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.publishToPublic({ id: 'm1', name: 'S', description: 'd', version: '2.0.0', category: 'c' })
    expect(apiMock.submitSkillForReview).toHaveBeenCalledWith(
      expect.objectContaining({ skill_id: 'm1', version: '2.0.0' }),
    )
  })

  it('渲染流转 tab 与空队列文案', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('流转确认')
    expect(wrapper.text()).toContain('暂无待确认流转')
    expect(apiMock.listSkillTransfers).toHaveBeenCalled()
  })

  it('回填 pending 流转卡（升级/初推 kind 徽标 + 源）', async () => {
    apiMock.listSkillTransfers.mockResolvedValue({
      data: {
        items: [
          { transfer_id: 't1', transfer_type: 'public_to_user', skill_id: 'shared', src_pool: 'public', src_owner: '', dst_pool: 'user', dst_owner: 'u:1', kind: 'upgrade', version: '1.2.0', name: 'Shared Tool', status: 'pending' },
        ],
        total: 1,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('Shared Tool')
    expect(wrapper.text()).toContain('升级')
    expect(wrapper.text()).toContain('源： public')
  })

  it('accept 调 API 并刷新队列', async () => {
    apiMock.listSkillTransfers.mockResolvedValue({
      data: {
        items: [{ transfer_id: 't9', transfer_type: 'agent_to_user', skill_id: 'gen', src_pool: 'agent', src_owner: 'a1', dst_pool: 'user', dst_owner: 'u:1', kind: 'initial', version: '1.0.0', name: 'Gen', status: 'pending' }],
        total: 1,
      },
    })
    apiMock.acceptSkillTransfer.mockResolvedValue({ code: 0 })
    const wrapper = mountPage()
    await flushPromises()
    const before = apiMock.listSkillTransfers.mock.calls.length
    const vm = wrapper.vm as any
    await vm.doAcceptTransfer({ transfer_id: 't9' })
    expect(apiMock.acceptSkillTransfer).toHaveBeenCalledWith('t9')
    expect(apiMock.listSkillTransfers.mock.calls.length).toBeGreaterThan(before)
  })

  it('reject 调 API', async () => {
    apiMock.rejectSkillTransfer.mockResolvedValue({ code: 0 })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.doRejectTransfer({ transfer_id: 't5' })
    expect(apiMock.rejectSkillTransfer).toHaveBeenCalledWith('t5')
  })
})

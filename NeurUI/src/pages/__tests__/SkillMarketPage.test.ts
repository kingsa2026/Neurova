/**
 * SkillMarketPage — 技能提交与审核 防回归测试（2026-09-01）
 *
 * 背景：市场端上架仅管理员直发，用户没有提交入口，管理员没有审核面板；
 * 版本更新通知虽有生产者但走契约断裂的旧通知端点。
 *
 * 契约（防回归）：
 * 1. 页面有「提交技能」入口 → 弹窗表单（skill_id/name/version/描述/
 *    分类/下载地址）→ POST /skill-pool/skills/submit（登录用户）
 * 2. 必填校验：skill_id/name 缺失时不提交
 * 3. 管理员可见「技能审核」面板：GET /skill-pool/skill-submissions 拉取
 *    待审列表，通过/拒绝 → POST /skill-submissions/{id}/review
 * 4. 非管理员不渲染审核面板、不拉取审核列表
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SkillMarketPage from '@/pages/SkillMarketPage.vue'

vi.mock('@/api/modules/skill-pool', () => ({
  getPublicSkills: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getPrivateSkills: vi.fn(),
  getSkill: vi.fn(),
  createSkill: vi.fn(),
  updateSkill: vi.fn(),
  deleteSkill: vi.fn(),
  installSkill: vi.fn().mockResolvedValue({ data: {} }),
  uninstallSkill: vi.fn(),
  submitSkillForReview: vi.fn().mockResolvedValue({ data: { id: 'subs_1', status: 'pending' } }),
  listSkillSubmissions: vi.fn().mockResolvedValue({
    data: {
      items: [
        {
          id: 'subs_1',
          skill_id: 'my-tool',
          name: 'My Tool',
          version: '1.0.0',
          description: 'A community skill',
          submitted_by: 'u1',
          submitted_by_name: 'alice',
          status: 'pending',
        },
      ],
      total: 1,
    },
  }),
  reviewSkillSubmission: vi.fn().mockResolvedValue({ data: { status: 'approved' } }),
  installSkillFromUrl: vi.fn(),
  installSkillFromZip: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import * as skillPoolApi from '@/api/modules/skill-pool'
import { useAuthStore } from '@/stores/auth'

const ADMIN = {
  id: 'a9',
  username: 'admin',
  email: 'admin@example.com',
  role: 'admin' as const,
  status: 'active' as const,
}
const USER = {
  id: 'u1',
  username: 'alice',
  email: 'alice@example.com',
  role: 'user' as const,
  status: 'active' as const,
}

const messages = {
  common: { refresh: '刷新' },
  market: {
    title: '技能市场',
    searchPlaceholder: '搜索',
    featured: '推荐',
    install: '安装',
    uninstall: '卸载',
    noSkills: '暂无技能',
    searchResults: '结果',
    allSkills: '所有技能',
    loadError: '加载失败',
    uninstallSuccess: '已卸载',
    installSuccess: '已安装',
    actionError: '操作失败',
    importZip: '导入 ZIP',
    installFromUrl: '远程安装',
    zipUploadTitle: 'ZIP',
    zipUploadDesc: '拖拽',
    urlInputTitle: 'URL',
    urlInputPlaceholder: 'URL',
    urlInputDesc: '支持 ZIP',
    submitSkill: '提交技能',
    submitConfirm: '提交审核',
    submitSkillId: '技能 ID',
    submitSkillIdPh: '唯一 ID',
    submitName: '技能名称',
    submitNamePh: '显示名',
    submitVersion: '版本',
    submitDesc: '描述',
    submitDescPh: '功能描述',
    submitCategory: '分类',
    submitUrl: '下载地址',
    submitUrlPh: 'ZIP 链接',
    submitSuccess: '已提交审核',
    submitError: '提交失败',
    submitMissingRequired: '请填写技能 ID 与名称',
    adminReview: '技能审核',
    reviewEmpty: '暂无待审核提交',
    reviewBy: '提交人',
    reviewApprove: '通过',
    reviewReject: '拒绝',
    reviewSuccess: '已审批',
    reviewError: '审批失败',
    reviewLoadError: '加载审核列表失败',
  },
}

const stubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: { props: ['title', 'subtitle'], template: '<div class="glass-card">{{ title }}<slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  'a-button': { props: ['type', 'danger', 'size'], emits: ['click'], template: '<button class="a-btn" @click="$emit(\'click\')"><slot/></button>' },
  'a-input-search': { props: ['value', 'placeholder'], emits: ['update:value', 'search'], template: '<input />' },
  'a-badge': { props: ['count'], template: '<span><slot/></span>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-list': {
    props: ['dataSource'],
    template: '<div class="a-list"><slot name="renderItem" v-for="(i, idx) in dataSource" :key="idx" :item="i" /></div>',
  },
  'a-list-item': { template: '<div class="a-list-item"><slot/><slot name="actions"/></div>' },
  'a-list-item-meta': { props: ['title', 'description'], template: '<div class="a-list-meta">{{ title }}</div>' },
  'a-modal': {
    props: ['open', 'title', 'okText'],
    emits: ['ok'],
    template: '<div v-if="open" class="ant-modal"><h3>{{ title }}</h3><slot/><button class="modal-ok" @click="$emit(\'ok\')">{{ okText }}</button></div>',
  },
  'a-form': { props: ['layout'], template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="form-item" :data-label="label"><slot/></div>' },
  'a-input': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], emits: ['update:value'], template: '<textarea class="ant-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-select': { props: ['value'], emits: ['update:value'], template: '<select />' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(SkillMarketPage, { global: { plugins: [i18n], stubs } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useAuthStore).mockReturnValue({ user: ADMIN } as any)
})

describe('SkillMarketPage 提交与审核', () => {
  it('普通用户:不渲染审核面板、不拉取待审列表,但保留提交入口', async () => {
    vi.mocked(useAuthStore).mockReturnValue({ user: USER } as any)
    const wrapper = mountPage()
    await flushPromises()

    expect(skillPoolApi.listSkillSubmissions).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('技能审核')
    expect(wrapper.text()).toContain('提交技能')
  })

  it('市场列表归一化: market 域 skill_id/downloads 映射渲染且安装用归一化 id', async () => {
    vi.mocked(skillPoolApi.getPublicSkills).mockResolvedValue({
      data: {
        items: [
          {
            skill_id: 'web-search',
            name: 'Web Search',
            description: '搜索互联网获取实时信息',
            downloads: 1200,
            category: 'utility',
          },
        ],
        total: 1,
      },
    } as any)
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('Web Search')
    const card = wrapper.find('.glass-card')
    const installBtn = card.findAll('button').find((b) => b.text().includes('安装'))
    await installBtn!.trigger('click')
    await flushPromises()
    expect(skillPoolApi.installSkill).toHaveBeenCalledWith('web-search', 'default')
  })

  it('管理员挂载时拉取待审列表并渲染审核面板', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(skillPoolApi.listSkillSubmissions).toHaveBeenCalledWith('pending')
    expect(wrapper.text()).toContain('技能审核')
    expect(wrapper.text()).toContain('My Tool')
  })

  it('提交弹窗：必填齐全时调用 submit 接口', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const submitBtn = wrapper.findAll('button').find((b) => b.text().includes('提交技能'))
    await submitBtn!.trigger('click')
    await flushPromises()

    const modal = wrapper.find('.ant-modal')
    expect(modal.exists()).toBe(true)

    const inputs = modal.findAll('input.ant-input')
    await inputs[0].setValue('my-tool')
    await inputs[1].setValue('My Tool')

    // stub a-modal 渲染 ok 按钮触发 @ok
    await modal.find('.modal-ok').trigger('click')
    await flushPromises()

    expect(skillPoolApi.submitSkillForReview).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(skillPoolApi.submitSkillForReview).mock.calls[0][0] as any
    expect(payload.skill_id).toBe('my-tool')
    expect(payload.name).toBe('My Tool')
  })

  it('提交弹窗：skill_id 缺失时不提交', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const submitBtn = wrapper.findAll('button').find((b) => b.text().includes('提交技能'))
    await submitBtn!.trigger('click')
    await flushPromises()

    const modal = wrapper.find('.ant-modal')
    const inputs = modal.findAll('input.ant-input')
    await inputs[1].setValue('Only Name')

    await modal.find('.modal-ok').trigger('click')
    await flushPromises()

    expect(skillPoolApi.submitSkillForReview).not.toHaveBeenCalled()
  })

  it('管理员审核：通过/拒绝走 review 接口', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const approveBtn = wrapper.findAll('button.a-btn').find((b) => b.text() === '通过')
    expect(approveBtn).toBeTruthy()
    await approveBtn!.trigger('click')
    await flushPromises()

    expect(skillPoolApi.reviewSkillSubmission).toHaveBeenCalledWith('subs_1', true)
  })
})

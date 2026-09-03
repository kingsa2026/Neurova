/**
 * NotificationPage + notifications store — 契约对齐防回归测试（2026-09-01）
 *
 * 背景：后端契约统一前，页面拿裸数组却按 res.data.items 解析（恒空）、
 * markRead/markAllRead 用 POST 打后端 PUT 路由（405）、铃铛未读数硬编码 0。
 * 二期：审批集成进通知中心——点卡片开详情，管理员就地审批。
 *
 * 契约（防回归）：
 * 1. GET /notifications 返回信封 {code, data:{items,total}}，条目字段
 *    id/type/created_at(ISO) —— 页面正确渲染列表与类型 tag
 * 2. markRead → POST /{id}/read；markAllRead → POST /mark-all-read
 * 3. store.fetchUnreadCount 从 data.total 更新徽标
 * 4. 业务类型（kb_review/skill_review/market_update…）有专属颜色，不崩
 * 5. 点击卡片 → 打开详情弹窗（标题/正文/负载数据）并标记已读
 * 6. 管理员在 kb_review 详情中可审批 → reviewKnowledgePublic(knowledge_id, approve, note)
 * 7. 管理员在 skill_review 详情中可审批 → reviewSkillSubmission(submission_id, approve, note)
 * 8. 审批成功后关闭弹窗并刷新列表；非管理员看不到审批按钮
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { setActivePinia, createPinia } from 'pinia'

const authHolder = vi.hoisted(() => ({
  user: { id: 'a9', username: 'admin', role: 'admin' } as Record<string, any> | undefined,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return authHolder.user
    },
  }),
}))

vi.mock('@/api/modules/notifications', () => ({
  getNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  deleteNotification: vi.fn(),
  getPushStats: vi.fn(),
}))

vi.mock('@/api/modules/knowledge', () => ({
  reviewKnowledgePublic: vi.fn().mockResolvedValue({ code: 0 }),
  listPublicSubmissions: vi.fn().mockResolvedValue({ data: [] }),
}))

vi.mock('@/api/modules/skill-pool', () => ({
  reviewSkillSubmission: vi.fn().mockResolvedValue({ code: 0 }),
}))

import NotificationPage from '@/pages/NotificationPage.vue'
import { useNotificationStore } from '@/stores/notifications'
import { markRead } from '@/api/modules/notifications'
import { reviewKnowledgePublic } from '@/api/modules/knowledge'
import { reviewSkillSubmission } from '@/api/modules/skill-pool'

const messages = {
  common: { all: 'All', refresh: '刷新', confirm: '确认', delete: '删除', noData: '暂无数据', success: '成功', error: '失败', markAllRead: '全部标记已读', markRead: '标记已读' },
  system: { notifications: '通知中心' },
  knowledge: { reviewApprove: '通过', reviewReject: '拒绝' },
  notification: {
    detailTitle: '通知详情',
    submitter: '提交人',
    knowledgeId: '知识 ID',
    skillId: '技能 ID',
    skillName: '技能名称',
    reviewNotePh: '审核意见（可留空）',
    reviewSuccess: '审核完成',
    reviewError: '审核操作失败',
    close: '关闭',
  },
}

const stubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel" @click="$emit(\'click\', $event)"><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  'a-badge': { props: ['count'], template: '<span class="a-badge" :data-count="count"><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-tag': { props: ['color'], template: '<span class="a-tag" :data-color="color"><slot/></span>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-pagination': { props: ['current', 'total', 'pageSize'], template: '<div class="a-pagination" />' },
  'a-popconfirm': { template: '<span><slot/></span>' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], emits: ['update:value'], template: '<textarea class="ant-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-modal': {
    props: ['open', 'title', 'footer'],
    template: '<div v-if="open" class="ant-modal"><h3>{{ title }}</h3><slot/></div>',
  },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(NotificationPage, { global: { plugins: [i18n], stubs } })
}

const makeEnvelope = () => ({
  code: 0,
  message: 'success',
  data: {
    items: [
      {
        id: 'n-1',
        type: 'kb_review',
        title: '知识库提交待审核',
        message: '用户 alice 提交「私有知识」到公共库',
        read: false,
        created_at: '2026-09-01T08:00:00+00:00',
        data: { knowledge_id: 'k1' },
      },
      {
        id: 'n-2',
        type: 'info',
        title: '欢迎',
        message: 'hello',
        read: true,
        created_at: '2026-09-01T07:00:00+00:00',
        data: {},
      },
    ],
    total: 2,
  },
})

import * as notifApi from '@/api/modules/notifications'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.mocked(notifApi.getNotifications).mockResolvedValue(makeEnvelope() as any)
  vi.mocked(notifApi.markRead).mockResolvedValue({ code: 0 } as any)
  vi.mocked(notifApi.markAllRead).mockResolvedValue({ code: 0 } as any)
})

describe('NotificationPage 契约', () => {
  it('解析信封 data.items 并渲染标题与业务类型 tag', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('知识库提交待审核')
    expect(text).toContain('欢迎')

    const tags = wrapper.findAll('.a-tag')
    expect(tags.length).toBe(2)
    expect(tags[0].attributes('data-color')).toBe('purple'), 'kb_review 有专属颜色'
  })

  it('未读数徽标来自列表（unread filter）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.a-badge').attributes('data-count')).toBe('1')
  })

  it('markRead 走 POST 契约', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const readBtn = wrapper.findAll('button').find((b) => b.text().trim() === '标记已读')
    await readBtn!.trigger('click')
    await flushPromises()
    expect(notifApi.markRead).toHaveBeenCalledWith('n-1')
  })

  it('markAllRead 走 POST /mark-all-read 契约', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const btn = wrapper.findAll('button').find((b) => b.text().trim() === '全部标记已读')
    await btn!.trigger('click')
    await flushPromises()
    expect(notifApi.markAllRead).toHaveBeenCalledTimes(1)
  })
})

describe('notifications store 未读徽标', () => {
  it('fetchUnreadCount 从 data.total 更新', async () => {
    vi.mocked(notifApi.getUnreadCount).mockResolvedValue({
      code: 0,
      data: { total: 3, unread_count: 3 },
    } as any)

    const store = useNotificationStore()
    await store.fetchUnreadCount()
    expect(store.unreadTotal).toBe(3)
    expect(store.hasUnread).toBe(true)
  })

  it('fetchNotifications 写入 items', async () => {
    const store = useNotificationStore()
    await store.fetchNotifications()
    expect(store.notifications).toHaveLength(2)
    expect(store.total).toBe(2)
  })
})

// ============ 二期：点击卡片详情 + 就地审批 ============

describe('NotificationPage 详情与审批', () => {
  beforeEach(() => {
    authHolder.user = { id: 'a9', username: 'admin', role: 'admin' }
  })

  it('点击卡片打开详情弹窗并标记已读', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const card = wrapper.findAll('.glass-panel.notification-item')[0]
    expect(card).toBeTruthy()
    await card.trigger('click')
    await flushPromises()

    const modal = wrapper.find('.ant-modal')
    expect(modal.exists()).toBe(true), '点卡片须打开详情弹窗'
    expect(wrapper.text()).toContain('通知详情')
    expect(modal.text()).toContain('知识库提交待审核')
    expect(modal.text()).toContain('k1'), '详情须展示负载数据'
    expect(markRead).toHaveBeenCalledWith('n-1'), '打开详情即标记已读'
  })

  it('管理员：kb_review 详情中审批通过 → reviewKnowledgePublic(knowledge_id, true, note)', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.findAll('.glass-panel.notification-item')[0].trigger('click')
    await flushPromises()

    const noteArea = wrapper.find('.ant-modal textarea.ant-textarea')
    await noteArea.setValue('质量不错')
    const approveBtn = wrapper.findAll('.ant-modal .glass-btn').find((b) => b.text() === '通过')
    expect(approveBtn).toBeTruthy(), 'kb_review 详情须有审批按钮'
    await approveBtn!.trigger('click')
    await flushPromises()

    expect(reviewKnowledgePublic).toHaveBeenCalledWith('k1', true, '质量不错')
  })

  it('管理员：skill_review 详情中拒绝 → reviewSkillSubmission(submission_id, false, note)', async () => {
    vi.mocked(notifApi.getNotifications).mockResolvedValue({
      code: 0,
      data: {
        items: [
          {
            id: 'n-9',
            type: 'skill_review',
            title: '技能提交待审核',
            message: '用户 alice 提交技能「My Tool」申请上架',
            read: false,
            created_at: '2026-09-01T08:00:00+00:00',
            data: { submission_id: 'subs_1', skill_id: 'my-tool', name: 'My Tool' },
          },
        ],
        total: 1,
      },
    } as any)

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.findAll('.glass-panel.notification-item')[0].trigger('click')
    await flushPromises()

    const rejectBtn = wrapper.findAll('.ant-modal .glass-btn').find((b) => b.text() === '拒绝')
    expect(rejectBtn).toBeTruthy(), 'skill_review 详情须有拒绝按钮'
    await rejectBtn!.trigger('click')
    await flushPromises()

    expect(reviewSkillSubmission).toHaveBeenCalledWith('subs_1', false, '')
  })

  it('审批成功后关闭弹窗并刷新列表', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.glass-panel.notification-item')[0].trigger('click')
    await flushPromises()

    const approveBtn = wrapper.findAll('.ant-modal .glass-btn').find((b) => b.text() === '通过')
    await approveBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.ant-modal').exists()).toBe(false), '审批成功后关闭详情'
    expect(notifApi.getNotifications).toHaveBeenCalledTimes(2), '列表须刷新'
  })

  it('非管理员：详情可看但无审批按钮', async () => {
    authHolder.user = { id: 'u1', username: 'alice', role: 'user' }
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.glass-panel.notification-item')[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.ant-modal').exists()).toBe(true)
    const approveBtn = wrapper.findAll('.ant-modal .glass-btn').find((b) => b.text() === '通过')
    expect(approveBtn).toBeUndefined(), '非管理员不应看到审批按钮'
  })
})

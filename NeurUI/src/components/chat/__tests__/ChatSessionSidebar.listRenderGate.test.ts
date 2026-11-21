/**
 * 关键列表渲染回归门（追平计划 E3）—— 会话侧栏
 *
 * E3 勘察登记：ChatSessionSidebar.vue 对 groupedSessions 全量 v-for
 * （每条挂下拉菜单），长会话历史的 DOM 行数无界。
 *
 * 修复策略（组件 → 策略 → 本文件用例）：
 * - 侧栏按渲染窗口分批显示（首屏 50 条，"加载更多"按钮每次 +50）；
 * - 会话列表整表重载（切 Agent）窗口归位；
 * - 拖拽重排只在顺序真变化时提交 reorderConsoleSessions（契约收全量
 *   ordered_ids，故提交仍为全量列表；"顺序未变不提交"由本文件钉住）。
 *
 * 门径：谁把侧栏改回全量 v-for、或删掉"加载更多"/顺序守卫，本文件即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const reorderConsoleSessionsMock = vi.fn()
vi.mock('@/api/modules/console', async () => ({
  ...(await vi.importActual<typeof import('@/api/modules/console')>('@/api/modules/console')),
  reorderConsoleSessions: (...args: unknown[]) => reorderConsoleSessionsMock(...args),
}))

// useSessionOps → useAgentPage 读路由拿 agentId；测试无真实路由，桩一个定值
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'agent-1' }, query: {} as Record<string, string> }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

import Antd from 'ant-design-vue'
import ChatSessionSidebar from '../ChatSessionSidebar.vue'
import { useChatStore } from '@/stores/chat'
import { useAgentStore } from '@/stores/agents'
import zhCN from '@/i18n/locales/zh-CN'

const BATCH = 50

function makeSessions(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `sess-${String(i).padStart(4, '0')}`,
    title: `会话 ${i}`,
    updatedAt: new Date(Date.now() - i * 3_600_000).toISOString(),
    pinned: false,
    sourceChannel: '',
    channelName: '',
  })) as any[]
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

/** 预置 n 条会话后挂载侧栏（agentStore 预置当前 agent，避开 loadAgents 网络面）。 */
function mountSidebar(n: number) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const chatStore = useChatStore()
  chatStore.setSessions(makeSessions(n))
  const agentStore = useAgentStore()
  ;(agentStore.agents as any[]).push({ id: 'agent-1', name: 'Agent A' } as any)
  agentStore.setCurrentAgent('agent-1')
  const wrapper = mount(ChatSessionSidebar, { global: { plugins: [i18n, pinia, Antd] } })
  return { wrapper, chatStore }
}

beforeEach(() => {
  vi.clearAllMocks()
  reorderConsoleSessionsMock.mockReset()
  reorderConsoleSessionsMock.mockResolvedValue({ data: {} })
})

describe('ChatSessionSidebar 会话列表渲染门（大数据集不退化为整表渲染）', () => {
  it('500 条会话首屏只渲染 50 条，其余折叠进「加载更多」入口', () => {
    const { wrapper } = mountSidebar(500)
    const rows = wrapper.findAll('.nr-session-item')
    expect(rows.length, '500 条会话首屏必须只渲染 50 条（渲染窗口有界）').toBe(BATCH)
    expect(rows[0].text()).toContain('会话 0')
    expect(rows[49].text()).toContain('会话 49')
    // 第 51 条不在首屏 DOM 里
    expect(wrapper.text()).not.toContain('会话 499')

    const moreBtn = wrapper.find('.nr-session-load-more')
    expect(moreBtn.exists(), '超出窗口时必须提供「加载更多」入口').toBe(true)
    expect(moreBtn.text()).toContain('450')
    wrapper.unmount()
  })

  it('点击「加载更多」按批放量：+50/次，耗尽后入口消失', async () => {
    const { wrapper } = mountSidebar(120)
    await wrapper.find('.nr-session-load-more').trigger('click')
    expect(wrapper.findAll('.nr-session-item').length).toBe(100)
    await wrapper.find('.nr-session-load-more').trigger('click')
    expect(wrapper.findAll('.nr-session-item').length, '两批后应渲染全部 120 条').toBe(120)
    expect(wrapper.find('.nr-session-load-more').exists(), '全部可见后入口应消失').toBe(false)
    wrapper.unmount()
  })

  it('会话列表整表重载（切 Agent）后窗口归位到首批', async () => {
    const { wrapper, chatStore } = mountSidebar(500)
    await wrapper.find('.nr-session-load-more').trigger('click')
    expect(wrapper.findAll('.nr-session-item').length).toBe(100)
    // 模拟切 Agent：setSessions 整表替换
    chatStore.setSessions(makeSessions(300))
    await flushPromises()
    expect(wrapper.findAll('.nr-session-item').length, '整表重载后窗口应归位 50').toBe(BATCH)
    wrapper.unmount()
  })

  it('搜索过滤与渲染窗口共存：命中子集正常显示', async () => {
    const { wrapper, chatStore } = mountSidebar(500)
    chatStore.setSearchQuery('会话 12')
    await flushPromises()
    const rows = wrapper.findAll('.nr-session-item')
    expect(rows.length, '搜索命中 11 条（会话 12x），应全部显示').toBe(11)
    expect(wrapper.find('.nr-session-load-more').exists(), '命中数在窗口内时无加载更多').toBe(false)
    wrapper.unmount()
  })
})

describe('ChatSessionSidebar 拖拽重排提交守卫（顺序真变化才落库）', () => {
  it('真实移位才提交 reorderConsoleSessions，且提交全量 ordered_ids', async () => {
    const { wrapper, chatStore } = mountSidebar(5)
    const items = () => wrapper.findAll('.nr-session-item')
    // 拖 sess-0000 放到 sess-0002 上 → 顺序变为 [1,2,0,3,4]
    await items()[0].trigger('dragstart')
    await items()[2].trigger('drop')
    await flushPromises()

    expect(reorderConsoleSessionsMock, '顺序真变化必须提交一次').toHaveBeenCalledTimes(1)
    const [agentId, orderedIds] = reorderConsoleSessionsMock.mock.calls[0] as [string, string[]]
    expect(agentId).toBe('agent-1')
    expect(orderedIds, '契约收全量列表：5 条会话 id 全量提交').toEqual([
      'sess-0001', 'sess-0002', 'sess-0000', 'sess-0003', 'sess-0004',
    ])
    expect(chatStore.sessions.map((s: any) => s.id)).toEqual([
      'sess-0001', 'sess-0002', 'sess-0000', 'sess-0003', 'sess-0004',
    ])
    wrapper.unmount()
  })

  it('顺序未变不提交：放到自身或原位（上方相邻项）不发起请求', async () => {
    const { wrapper } = mountSidebar(5)
    const items = () => wrapper.findAll('.nr-session-item')
    // 放到自身
    await items()[1].trigger('dragstart')
    await items()[1].trigger('drop')
    expect(reorderConsoleSessionsMock, '放到自身=顺序未变，不提交').not.toHaveBeenCalled()
    // 拖 sess-0001 放到 sess-0000 上：s1 本就紧跟 s0，顺序未变 → 不提交
    await items()[1].trigger('dragstart')
    await items()[0].trigger('drop')
    await flushPromises()
    expect(reorderConsoleSessionsMock, '放回原位=顺序未变，不提交').not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

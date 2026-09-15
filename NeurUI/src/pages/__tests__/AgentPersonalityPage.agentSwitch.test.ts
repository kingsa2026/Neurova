/**
 * AgentPersonalityPage — agent 切换联动契约（bugfix 2026-09-15）
 *
 * 症状：在人格页面切换 agent，页面数据不切换。
 * 根因：
 *  1. 页面未接 useAgentPage 的 onAgentChange，agentId 变化后不重拉（同页族的
 *     Memory/Metacognition/Reflection/Growth 页均已接线）；
 *  2. 个性页签 fetch/save/evolve 裸调 /growth/personality* 不带 agent_id
 *     （后端按 Query 参数取 agent，缺省落 "default"），即使重拉仍显示
 *     default 的数据，保存还会把当前 agent 的人格写进 default 的文件。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

// ── 可控的 useAgentPage：模拟真实 composable 契约 ──
// 真实实现：options.onAgentChange 在 agentId 变化时被调用。
// 测试里切 agent = 改 agentId.value + 触发注册的回调。
let pageAgentId: ReturnType<typeof ref<string>> | undefined
let registeredOnAgentChange: ((id: string) => void) | undefined

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: (options?: { onAgentChange?: (id: string) => void }) => {
    registeredOnAgentChange = options?.onAgentChange
    pageAgentId ??= ref('agent-A')
    return {
      agentId: pageAgentId,
      currentAgent: ref({ name: 'A' }),
      agentLoading: ref(false),
    }
  },
}))

vi.mock('@/api/modules/memory', () => ({
  getEmotionSummary: vi.fn(),
}))

vi.mock('@/api/modules/growth', () => ({
  getMotivation: vi.fn().mockResolvedValue({ code: 0, data: null }),
  getPersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
}))

vi.mock('@/api', () => ({
  request: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import AgentPersonalityPage from '@/pages/AgentPersonalityPage.vue'
import { getEmotionSummary } from '@/api/modules/memory'
import { request } from '@/api'

const zhMessages = {
  nav: { persona: '人格', emotion: '情绪', personality: '个性' },
  common: { refresh: '刷新', edit: '编辑', cancel: '取消', save: '保存', success: 'ok', error: 'err', noData: '暂无数据', updated: '更新于' },
  emotion: { title: '情绪', analysis: '情绪分析', share: '占比 ', entries: '条', neutral: '中性', joy: '开心' },
  growth: { motivation: '动力状态', personality: '个性档案', traits: '特质', evolve: '进化' },
  personality: {
    openness: '开放性', conscientiousness: '尽责性', extraversion: '外向性',
    agreeableness: '宜人性', neuroticism: '神经质', creativity: '创造力',
  },
}

const globalStubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h4>{{title}}</h4><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div class="glass-stat"></div>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{description}}</div>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-tag': { props: ['color'], template: '<span><slot/></span>' },
  'a-slider': { props: ['value'], template: '<div class="slider-stub"/>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhMessages } })
  return mount(AgentPersonalityPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

/** 模拟用户在 AgentSwitcher 里切换到 agent-B（等价真实链路：store → useAgentPage 的 agentId + 回调） */
async function switchToAgentB() {
  pageAgentId!.value = 'agent-B'
  registeredOnAgentChange?.('agent-B')
  await flushPromises()
}

describe('AgentPersonalityPage agent 切换联动', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pageAgentId = undefined
    registeredOnAgentChange = undefined
    vi.mocked(request.get).mockResolvedValue({ data: {} } as any)
    vi.mocked(request.put).mockResolvedValue({ data: {} } as any)
    vi.mocked(request.post).mockResolvedValue({ data: {} } as any)
    vi.mocked(getEmotionSummary).mockResolvedValue({
      code: 0,
      data: { total_annotated: 1, emotion_distribution: { joy: 1 } },
      message: 'ok',
    } as any)
  })

  it('挂载即按当前 agent 拉数：情绪摘要与个性页签都带 agent_id=agent-A', async () => {
    mountPage()
    await flushPromises()
    expect(getEmotionSummary).toHaveBeenCalledWith('agent-A')
    // 个性页签走 axios 包装 request —— 第二参数必须带 agent_id query
    const g = vi.mocked(request.get).mock.calls.find((c) => c[0] === '/growth/personality')
    expect(g, '个性页签应 GET /growth/personality').toBeTruthy()
    expect((g![1] as any)?.params?.agent_id).toBe('agent-A')
  })

  it('页面必须注册 onAgentChange（切换 agent 的数据联动总闸）', async () => {
    mountPage()
    await flushPromises()
    expect(registeredOnAgentChange, 'useAgentPage 需传 onAgentChange，否则切换 agent 页面不重拉').toBeTypeOf('function')
  })

  it('切换 agent 后全页重拉：情绪摘要按新 agent 重查', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getEmotionSummary).mockClear()
    await switchToAgentB()
    expect(getEmotionSummary).toHaveBeenCalledWith('agent-B')
    expect(wrapper.exists()).toBe(true)
  })

  it('切换 agent 后个性页签重拉且带新 agent_id', async () => {
    mountPage()
    await flushPromises()
    vi.mocked(request.get).mockClear()
    await switchToAgentB()
    const g = vi.mocked(request.get).mock.calls.find((c) => c[0] === '/growth/personality')
    expect(g, '切换后应重新 GET /growth/personality').toBeTruthy()
    expect((g![1] as any)?.params?.agent_id).toBe('agent-B')
  })

  it('保存个性写到当前 agent（防串数据）：PUT 带 agent_id 且落在编辑后的 agent', async () => {
    const wrapper = mountPage()
    await flushPromises()

    // 进入编辑态 → 保存
    const editBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '编辑')
    expect(editBtn, '个性页签应有编辑按钮').toBeTruthy()
    await editBtn!.trigger('click')
    const saveBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '保存')
    expect(saveBtn).toBeTruthy()
    vi.mocked(request.put).mockClear()
    await saveBtn!.trigger('click')
    await flushPromises()

    const put = vi.mocked(request.put).mock.calls.find((c) => c[0] === '/growth/personality')
    expect(put, '保存应 PUT /growth/personality').toBeTruthy()
    // 第三参（axios config）携带 agent_id；body 只放 traits
    expect((put![2] as any)?.params?.agent_id).toBe('agent-A')
    expect((put![1] as any)?.agent_id, 'agent_id 不应混进 body（后端只认 Query）').toBeUndefined()
  })

  it('进化人格也按当前 agent 调用（同一端点族契约）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const evolveBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '进化')
    expect(evolveBtn, '个性页签应有进化按钮').toBeTruthy()
    vi.mocked(request.post).mockClear()
    await evolveBtn!.trigger('click')
    await flushPromises()
    const post = vi.mocked(request.post).mock.calls.find((c) => c[0] === '/growth/personality/evolve')
    expect(post).toBeTruthy()
    expect((post![2] as any)?.params?.agent_id).toBe('agent-A')
  })
})

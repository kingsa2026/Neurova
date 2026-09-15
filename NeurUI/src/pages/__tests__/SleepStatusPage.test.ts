/**
 * SleepStatusPage — 睡眠四页签契约（2026-09-15 补齐 A 验收）
 *
 * 钉住验收发现的断点修复：
 * 1. 梦境卡字段错位：后端 dream_type/timestamp(秒)/insights_generated(数)
 *    → 前端此前读 item.type/created_at/insights[]，有数据也渲染不出；
 * 2. 洞察卡：后端 /insights 无 apply 端点，"应用洞察"是假按钮（点击 404）；
 * 3. 合并卡：data-source 硬编码 [] 从不取数 —— /merges 有真实数据；
 * 4. 冲突卡：引擎审计恒 resolved=True + resolution 合法集
 *    (keep_longest/keep_newest/merge)，前端 local/remote 为非法值；
 * 5. isInSleep 派生：自动睡眠(is_sleeping=False, phase=deep_sleep)时
 *    页头显示"睡眠中"+唤醒按钮（/wake 端点已回落 tracker）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: ref('default'), currentAgent: ref({ name: 'N' }), agentLoading: ref(false) }),
}))

vi.mock('@/composables/usePolling', () => ({
  usePolling: (fn: any) => ({ loading: ref(false), start: vi.fn(), stop: vi.fn(), poll: fn }),
}))

vi.mock('@/api/modules/sleep', async (importOriginal) => {
  const actual = await importOriginal<any>()
  return {
    ...actual,
    getSleepStatus: vi.fn(),
    getDreams: vi.fn(),
    getSleepInsights: vi.fn(),
    getMemoryMerges: vi.fn(),
    getMergeConflicts: vi.fn(),
    resolveConflict: vi.fn().mockResolvedValue({}),
    putToSleep: vi.fn().mockResolvedValue({}),
    wakeUp: vi.fn().mockResolvedValue({}),
  }
})

vi.mock('ant-design-vue', async (importOriginal) => {
  const actual = await importOriginal<any>()
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }
})

import SleepStatusPage from '@/pages/SleepStatusPage.vue'
import { getSleepStatus, getDreams, getSleepInsights, getMemoryMerges, getMergeConflicts, resolveConflict } from '@/api/modules/sleep'

const TS = 1769999000

const messages = {
  common: { refresh: '刷新', noData: '暂无数据', all: '全部', success: 'ok', error: 'err' },
  nav: { sleepstatus: '睡眠状态', sleepsettings: '睡眠设置' },
  sleep: {
    status: '睡眠状态', sleeping: '睡眠中', awake: '清醒', phase: '阶段', lastSleep: '上次入睡',
    duration: '时长', nextWake: '预计唤醒', wake: '唤醒', sleepAction: '进入睡眠',
    dreams: '梦境', insights: '洞察', merges: '记忆合并', conflicts: '冲突解决',
    lightPhase: '浅睡', deepPhase: '深睡', remPhase: 'REM', hibernatePhase: '休眠',
    consolidation: '整理', creative: '创造', problemSolving: '问题求解', replay: '回放',
    localValue: '本地值', remoteValue: '远程值', resolved: '已解决', pending: '待处理',
    keepStrongest: '保留最长', keepNewest: '保留最新', mergeOption: '合并',
    applyToStore: '写回记忆库', currentStrategy: '当前策略', changeStrategy: '改策略',
    insightsN: '{n} 条洞察', mergedSources: '合并 {n} 条 →',
  },
}

const globalStubs = {
  GlassPanel: { props: ['variant', 'glow'], template: '<div><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h4 class="card-title">{{ title }}</h4><slot/><slot name="extra"/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  AgentPageTabs: { props: ['tabs'], template: '<div/>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-tag': { props: ['color', 'size'], template: '<span class="a-tag"><slot/></span>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-select': { props: ['value', 'placeholder'], template: '<div><slot/></div>' },
  'a-select-option': { props: ['value'], template: '<option><slot/></option>' },
  'a-space': { template: '<div><slot/></div>' },
  'a-list': {
    props: ['dataSource'],
    template: '<div class="a-list"><slot name="renderItem" v-for="(item, i) in (dataSource || [])" :key="i" :item="item" :index="i"/><slot name="empty" v-if="!(dataSource || []).length"/></div>',
  },
  'a-list-item': { template: '<div class="a-list-item"><slot/></div>' },
  'a-checkbox': { props: ['checked'], emits: ['update:checked', 'change'], template: '<label class="a-checkbox"><input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)"/><slot/></label>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(SleepStatusPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

beforeEach(() => {
  vi.clearAllMocks()
  // 自动睡眠：is_sleeping=false 但 tracker 阶段=deep_sleep（统一源契约）
  vi.mocked(getSleepStatus).mockResolvedValue({
    agent_id: 'default', is_sleeping: false, sleep_phase: 'deep_sleep',
    last_sleep_time: TS, total_sleep_duration: 120, sleep_cycles: 2, next_wake: TS + 3600,
  } as never)
  vi.mocked(getDreams).mockResolvedValue([
    { dream_id: 'd1', agent_id: 'default', timestamp: TS, dream_type: 'replay',
      content: '整理 3 条记忆，合并 1 组，归档 0 条', memories_involved: ['m1'], insights_generated: 1, duration: 0.2 },
  ] as never)
  vi.mocked(getSleepInsights).mockResolvedValue([
    { insight_id: 'i1', dream_id: 'd1', agent_id: 'default', timestamp: TS, insight_type: 'pattern',
      content: '2 条同类记忆收敛为 1 条', confidence: 0.7, related_memories: ['m1', 'm2'] },
  ] as never)
  vi.mocked(getMemoryMerges).mockResolvedValue([
    { merge_id: 'mg-1', agent_id: 'default', timestamp: TS, source_memories: ['m1', 'm2'],
      source_total: 2, target_memory: 'mg-1', merge_type: 'consolidation', success: true, conflicts_resolved: 0 },
  ] as never)
  vi.mocked(getMergeConflicts).mockResolvedValue([
    { id: 'cr_1', agent_id: 'default', field: 'content', local_value: 'A', remote_value: 'B',
      resolved: true, resolution: 'keep_longest', created_at: TS },
  ] as never)
})

describe('SleepStatusPage 四页签契约', () => {
  it('梦境卡按后端真实字段渲染（dream_type/timestamp），回放类型有 i18n 标签', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('整理 3 条记忆')
    expect(html).toContain('回放')
  })

  it('洞察卡渲染真实字段，且没有指向不存在端点的"应用"假按钮', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('2 条同类记忆收敛为 1 条')
    expect(html).not.toContain('applyInsight') // 假按钮连键名都不应再出现
  })

  it('合并卡必须取 /merges 真实数据（此前 data-source 硬编码空）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(getMemoryMerges).toHaveBeenCalledWith('default', expect.objectContaining({ limit: 20 }))
    expect(wrapper.html()).toContain('mg-1')
  })

  it('冲突卡展示当前策略并可改为后端合法值；默认不写回、勾选后 apply_to_store=true', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('保留最长') // currentStrategy keep_longest 映射

    const mergeBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '合并')
    expect(mergeBtn, '应有 合并(merge) 策略按钮').toBeTruthy()
    await mergeBtn!.trigger('click')
    await flushPromises()
    expect(resolveConflict).toHaveBeenLastCalledWith('default', 'cr_1', 'merge', false)

    // 勾选写回
    await wrapper.find('.a-checkbox input[type=checkbox]').setValue(true)
    await flushPromises()
    await mergeBtn!.trigger('click')
    await flushPromises()
    expect(resolveConflict).toHaveBeenLastCalledWith('default', 'cr_1', 'merge', true)
  })

  it('自动睡眠(is_sleeping=false,phase=deep_sleep)页头显示睡眠中并可唤醒', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('睡眠中')
    const wakeBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '唤醒')
    expect(wakeBtn, '自动睡眠期也应能唤醒（/wake 已回落 tracker）').toBeTruthy()
  })

  it('相位可视化按链序 浅睡→REM→深睡→休眠', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const names = wrapper.findAll('.phase-name').map((n) => n.text())
    expect(names).toEqual(['浅睡', 'REM', '深睡', '休眠'])
    // deep_sleep 当前相位：浅睡/REM 已完成、深睡为活跃位
    const steps = wrapper.findAll('.phase-step')
    expect(steps.map((s) => s.classes().includes('completed'))).toEqual([true, true, false, false])
  })
})

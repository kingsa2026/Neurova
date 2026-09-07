import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ContextUsageIndicator from '../chat/ContextUsageIndicator.vue'

// api mock：/context/composition 返回固定快照
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: {
        agent_id: 'default',
        total_tokens: 124000,
        context_window: 1000000,
        messages: {
          buckets: {
            system: { count: 1, tokens: 83000 },
            user: { count: 20, tokens: 10000 },
            assistant: { count: 20, tokens: 9000 },
            tool: { count: 5, tokens: 1000 },
            other: { count: 0, tokens: 0 },
          },
          total_tokens: 103000,
        },
        tools: {
          mcp: { count: 10, tokens: 11000 },
          system: { count: 6, tokens: 6000 },
          skill: { count: 3, tokens: 3000 },
          other: { count: 0, tokens: 0 },
        },
        cache_hit_rate: 0.877,
        cache_source: 'prefix_estimate',
      },
    }),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      chat: {
        ctxPanelTitle: '上下文容量',
        ctxCacheHitRate: '平均缓存命中率',
        ctxSectionMessages: '消息',
        ctxSectionSystemTools: '系统工具',
        ctxSectionMcpTools: 'MCP 工具',
        ctxSectionOther: '其他',
        ctxSectionSkills: '技能',
        ctxSectionSystemPrompt: '系统提示词',
        usagePrompt: '输入 {n}',
        usageCompletion: '输出 {n}',
        usageContextPct: '上下文 {pct}%',
      },
    },
  },
})

interface IndicatorProps {
  usage?: { prompt: number; completion: number; total: number } | null
  contextWindow?: number | null
  agentId?: string | null
  sessionId?: string | null
}

async function mountIndicator(props: IndicatorProps = {}) {
  const wrapper = mount(ContextUsageIndicator, {
    props: { usage: null, ...props },
    global: { plugins: [i18n] },
  })
  await flushPromises()
  return wrapper
}

describe('ContextUsageIndicator 可见性（2026-09-07 环图消失根因修复）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('有 usage 时渲染环图', async () => {
    const wrapper = await mountIndicator({
      usage: { prompt: 100, completion: 50, total: 150 },
      contextWindow: 1000,
      agentId: 'default',
    })
    expect(wrapper.find('.nr-ctx-usage').exists()).toBe(true)
    expect(wrapper.find('.nr-ctx-ring').exists()).toBe(true)
  })

  it('usage 为空时拉 composition 兜底渲染（根因：原 v-if="usage" 刷新即消失）', async () => {
    const wrapper = await mountIndicator({ usage: null, agentId: 'default' })
    expect(wrapper.find('.nr-ctx-usage').exists()).toBe(true)
    expect(wrapper.find('.nr-ctx-ring').exists()).toBe(true)
    // 文本来自 composition.total_tokens=124000 → 12.4万
    expect(wrapper.find('.nr-ctx-usage-text').text()).toBe('12.4万')
  })

  it('usage 与 composition 都为空且无 agent → 不渲染', async () => {
    const wrapper = await mountIndicator({ usage: null })
    expect(wrapper.find('.nr-ctx-usage').exists()).toBe(false)
  })

  it('悬停展开明细面板：分段行 + 命中率', async () => {
    const wrapper = await mountIndicator({ usage: null, agentId: 'default' })
    await wrapper.find('.nr-ctx-usage').trigger('mouseenter')
    await flushPromises()
    const panel = wrapper.find('.nr-ctx-panel')
    expect(panel.exists()).toBe(true)
    const rows = wrapper.findAll('.nr-ctx-panel-row')
    expect(rows.length).toBeGreaterThanOrEqual(4)
    const footer = wrapper.find('.nr-ctx-panel-footer')
    expect(footer.exists()).toBe(true)
    expect(footer.text()).toContain('87.7')
  })
})

// U7 双时态时间线（只读视图）：access/query 双时态读面 → valid 区间条 +
// 当前时刻指示；mock 网络层，断言区间数量、now 线与 asOf 联动、三态。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioBitemporalTimeline from '../StudioBitemporalTimeline.vue'
import { accessQuery } from '@/api/modules/ontology'

vi.mock('@/api/modules/ontology', () => ({
  accessQuery: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { loading: '加载中...', search: '搜索', clear: '清除' },
      ontology: {
        timelineTitle: '双时态时间线',
        timelineRefresh: '刷新',
        timelineEmpty: '暂无事实区间',
        timelineLoadFailed: '双时态时间线加载失败',
        timelineNow: '当前时刻',
        timelineOpenEnd: '生效中（未闭合）',
        timelineNoStart: '起点未记录',
        asOfLabel: 'asOf（业务时间）',
      },
    },
  },
})

function fact(id: string, meta: Record<string, unknown>) {
  return { id, knowledge_id: id, title: '', content: '', created_at: 0, metadata: meta }
}

const ITEMS = [
  fact('f1', { subject_key: '客户A', predicate_term_id: 'is_a', object_term: 'VIP',
    valid_from: '2026-01-01T00:00:00Z', valid_until: '2026-06-01T00:00:00Z' }),
  fact('f2', { subject_key: '客户B', predicate_term_id: 'is_a', object_term: '黑名单',
    valid_from: '2026-03-01T00:00:00Z', valid_until: '' }),
  fact('f3', { subject_key: '客户C', predicate_term_id: 'x', object_term: 'y',
    valid_from: '', valid_until: '' }),
]

const STUBS = {
  'a-alert': { props: ['message'], template: '<div class="ant-alert">{{ message }}</div>' },
  'a-empty': { props: ['description'], template: '<div class="ant-empty">{{ description }}</div>' },
}

function mountTimeline() {
  return mount(StudioBitemporalTimeline, {
    global: { plugins: [i18n], stubs: STUBS },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(accessQuery).mockResolvedValue(ITEMS as never)
})

describe('StudioBitemporalTimeline', () => {
  it('renders one interval bar per fact with a parseable valid_from, plus the now line', async () => {
    const wrapper = mountTimeline()
    await flushPromises()
    const bars = wrapper.findAll('[data-testid="timeline-interval"]')
    expect(bars).toHaveLength(2) // f1/f2 有起点；f3 起点未记录不渲染区间条
    expect(bars[0].attributes('data-fact-id')).toBe('f1')
    expect(bars[1].attributes('data-fact-id')).toBe('f2')
    expect(bars[1].classes()).toContain('bar--open') // valid_until 为空＝开放区间
    expect(wrapper.find('[data-testid="timeline-now-line"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="timeline-axis"]').exists()).toBe(true)
  })

  it('shows the no-start note for facts lacking valid_from', async () => {
    const wrapper = mountTimeline()
    await flushPromises()
    expect(wrapper.text()).toContain('起点未记录')
  })

  it('re-queries with asOf when the user applies the asOf axis', async () => {
    const wrapper = mountTimeline()
    await flushPromises()
    await wrapper.find('[data-testid="timeline-asof-input"]').setValue('2026-05-01T00:00')
    await wrapper.find('[data-testid="timeline-asof-apply"]').trigger('click')
    await flushPromises()
    const lastCall = vi.mocked(accessQuery).mock.calls.at(-1)?.[0] as { asOf?: string; knownAt?: string }
    expect(lastCall.asOf).toBe('2026-05-01T00:00')
    expect(lastCall.knownAt).toBeTruthy()
    expect(wrapper.find('[data-testid="timeline-asof-line"]').exists()).toBe(true)
  })

  it('clears the asOf axis and reloads the current snapshot', async () => {
    const wrapper = mountTimeline()
    await flushPromises()
    await wrapper.find('[data-testid="timeline-asof-input"]').setValue('2026-05-01T00:00')
    await wrapper.find('[data-testid="timeline-asof-apply"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="timeline-asof-clear"]').trigger('click')
    await flushPromises()
    const lastCall = vi.mocked(accessQuery).mock.calls.at(-1)?.[0] as { asOf?: string }
    expect(lastCall.asOf).toBeUndefined()
    expect(wrapper.find('[data-testid="timeline-asof-line"]').exists()).toBe(false)
  })

  it('shows empty state when no facts come back', async () => {
    vi.mocked(accessQuery).mockResolvedValue([] as never)
    const wrapper = mountTimeline()
    await flushPromises()
    expect(wrapper.find('[data-testid="timeline-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无事实区间')
  })

  it('shows error state when the query fails', async () => {
    vi.mocked(accessQuery).mockRejectedValue(new Error('boom'))
    const wrapper = mountTimeline()
    await flushPromises()
    expect(wrapper.find('[data-testid="timeline-error"]').exists()).toBe(true)
  })

  it('shows loading state while the query is in flight', async () => {
    vi.mocked(accessQuery).mockReturnValue(new Promise(() => {}) as never)
    const wrapper = mountTimeline()
    await flushPromises()
    expect(wrapper.find('[data-testid="timeline-loading"]').exists()).toBe(true)
  })
})

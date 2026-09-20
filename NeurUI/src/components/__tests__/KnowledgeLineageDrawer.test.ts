/**
 * KnowledgeLineageDrawer — 事实血缘抽屉（工单 024 / G01 用户可见面）
 *
 * 契约：
 * 1. 断言跳要能一路看到**原始陈述文本**（"谁、何时、在哪份介质上说了什么"）；
 * 2. 缺维必须显式说出来：没有断言与"有断言但内容正常"在界面上必须长得不一样，
 *    隐藏空白区等于把"没溯源"演成"已溯源"；
 * 3. 推导跳列出前提及其原文，点前提事件抛给父层（不叠抽屉，换当前事实）；
 * 4. 没取到血缘时是空态，不是一条装出来的空链。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import KnowledgeLineageDrawer from '@/components/KnowledgeLineageDrawer.vue'
import zhCN from '@/i18n/locales/zh-CN'

const api = vi.hoisted(() => ({
  getFactLineage: vi.fn(),
  getFactTurtle: vi.fn(),
}))

vi.mock('@/api/modules/knowledge', () => api)

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

function lineage(overrides: Record<string, unknown> = {}) {
  return {
    fact_id: 'fact_1', subject_key: 'subj_1', subject_label: '青海湖', predicate: 'is_a',
    object_term: '湖泊', record_kind: 'triple', status: 'active', recorded_at: '2026-09-21',
    qualifier: {}, confidence: 0.8, derivation: null, missing: [],
    provenance_state: 'evidenced',
    hops: [{
      kind: 'assertion', assertion_id: 'asrt_1', actor_type: 'user', actor_id: 'u1',
      medium_ref: 'https://example.test/a', statement_text: '青海湖是高原湖泊',
      asserted_at: '2026-09-21T00:00:00+00:00', activity_id: 'act_1',
      activity_kind: 'admit', activity_basis: '', seq: 1, digest: 'd1',
    }],
    ...overrides,
  }
}

function mountDrawer(props: Record<string, unknown> = {}) {
  return mount(KnowledgeLineageDrawer, {
    props: { open: true, factId: 'fact_1', ...props },
    global: {
      plugins: [i18n],
      stubs: {
        'a-drawer': { template: '<div><slot /></div>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-empty': { template: '<div class="empty">{{ $props.description }}</div>' },
        'a-alert': {
          props: ['message', 'description'],
          template: '<div class="alert">{{ message }}：{{ description }}</div>',
        },
        'a-tag': { template: '<span class="tag"><slot /></span>' },
        'a-timeline': { template: '<div><slot /></div>' },
        'a-timeline-item': { template: '<div class="hop"><slot /></div>' },
        'a-button': { template: '<button><slot /></button>' },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getFactLineage.mockResolvedValue(lineage())
})

describe('原始陈述可见', () => {
  it('断言跳带出正文、来源介质与管线', async () => {
    const wrap = mountDrawer()
    await flushPromises()

    expect(api.getFactLineage).toHaveBeenCalledWith('fact_1')
    expect(wrap.text()).toContain('青海湖是高原湖泊')
    expect(wrap.text()).toContain('https://example.test/a')
    expect(wrap.text()).toContain('admit')
  })

  it('链位随断言一起显示，摘要巡检的读数才接得上', async () => {
    const wrap = mountDrawer()
    await flushPromises()

    expect(wrap.text()).toContain('#1')
  })
})

describe('缺维显式', () => {
  it('没有断言的事实说出缺了哪一维，而不是显示一片空白', async () => {
    api.getFactLineage.mockResolvedValue(lineage({
      hops: [], missing: ['assertions'], provenance_state: 'unevidenced',
    }))

    const wrap = mountDrawer()
    await flushPromises()

    expect(wrap.find('.alert').exists()).toBe(true)
    expect(wrap.text()).toContain('没有任何断言')
    expect(wrap.text()).toContain('尚无依据')
    expect(wrap.find('.empty').exists()).toBe(true)
  })

  it('来源介质没记时单独报这一维', async () => {
    api.getFactLineage.mockResolvedValue(lineage({ missing: ['medium_ref'] }))

    const wrap = mountDrawer()
    await flushPromises()

    expect(wrap.text()).toContain('活动未记来源介质')
  })
})

describe('推导跳', () => {
  it('列出前提并把前提的原始陈述一起带出来', async () => {
    api.getFactLineage.mockResolvedValue(lineage({
      derivation: { rule_id: 'trans', rule_version: 'v1', stratum: 0 },
      hops: [{
        kind: 'derivation', rule: { rule_id: 'trans', version: 'v1', head_predicate: 'part_of' },
        rule_ids: ['trans'],
        premises: [
          { fact_id: 'fact_a', subject_label: '甲', predicate: 'part_of', object_term: '乙',
            statement_texts: ['甲是乙的一部分'] },
          { fact_id: 'fact_b', subject_label: '乙', predicate: 'part_of', object_term: '丙',
            statement_texts: [] },
        ],
      }],
    }))

    const wrap = mountDrawer()
    await flushPromises()

    expect(wrap.text()).toContain('由规则 trans 推出')
    expect(wrap.text()).toContain('甲是乙的一部分')
    // 没有原文的前提要单独说缺，不能安静地什么都不写
    expect(wrap.findAll('.hop-gap').length).toBe(1)
  })

  it('点前提向上抛 open-fact，由父层换当前事实', async () => {
    api.getFactLineage.mockResolvedValue(lineage({
      hops: [{
        kind: 'derivation', rule: { rule_id: 'trans', version: 'v1', head_predicate: 'part_of' },
        rule_ids: ['trans'],
        premises: [{ fact_id: 'fact_a', subject_label: '甲', predicate: 'part_of',
                     object_term: '乙', statement_texts: ['甲是乙的一部分'] }],
      }],
    }))

    const wrap = mountDrawer()
    await flushPromises()
    await wrap.find('.premise-link').trigger('click')

    expect(wrap.emitted('open-fact')?.[0]).toEqual(['fact_a'])
  })
})

describe('导出与空态', () => {
  it('导出走后端那份 Turtle 文本，前端不重排', async () => {
    api.getFactTurtle.mockResolvedValue('@prefix kbg: <x> .\nkbg:s kbg:p "o"@zh .\n')
    global.URL.createObjectURL = vi.fn(() => 'blob:x')
    global.URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrap = mountDrawer()
    await flushPromises()
    await wrap.findAll('button').at(-1)!.trigger('click')
    await flushPromises()

    expect(api.getFactTurtle).toHaveBeenCalledWith('fact_1')
    expect(click).toHaveBeenCalled()
    click.mockRestore()
  })

  it('没取到血缘是空态，不是一条装出来的空链', async () => {
    const wrap = mountDrawer({ open: true, factId: '' })
    await flushPromises()

    expect(api.getFactLineage).not.toHaveBeenCalled()
    expect(wrap.find('.hop').exists()).toBe(false)
  })
})

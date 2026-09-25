/**
 * KnowledgePage — 冲突队列两条轴（工单 016）
 *
 * 契约：
 * 1. 条目侧（同值）与治理层（事实分歧）共用一个队列，靠 `axis` 判别；条目侧原有渲染不破。
 * 2. 事实侧必须露出 kind / severity / 建议策略 / policy_basis —— 治理者要能看懂凭什么建议。
 * 3. **没有"自动裁决"这条路**：policy_basis 缺失要标红，`supersede_old` 在未指明胜方前禁用，
 *    指明后才带着 winner_fact_id 发出去。只写一个 resolution 字符串是假干净。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent } from 'vue'
import KnowledgePage from '@/pages/KnowledgePage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const api = vi.hoisted(() => ({
  getKnowledgeNodes: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  searchKnowledge: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  createKnowledgeNode: vi.fn(),
  updateKnowledgeNode: vi.fn(),
  deleteKnowledgeNode: vi.fn(),
  hybridKnowledgeSearch: vi.fn(),
  shareKnowledgeNode: vi.fn(),
  submitKnowledgeToPublic: vi.fn(),
  listPublicSubmissions: vi.fn().mockResolvedValue({ data: [] }),
  reviewKnowledgePublic: vi.fn(),
  listKbConfigs: vi.fn().mockResolvedValue({ data: { configs: [] } }),
  createKbConfig: vi.fn(),
  deleteKbConfig: vi.fn(),
  listKbCollections: vi.fn().mockResolvedValue({ data: { collections: [] } }),
  createKbCollection: vi.fn(),
  deleteKbCollection: vi.fn(),
  listKnowledgeChunks: vi.fn().mockResolvedValue({ data: [] }),
  listKnowledgeChunkRevisions: vi.fn().mockResolvedValue({ data: [] }),
  updateKnowledgeChunk: vi.fn(),
  previewChunking: vi.fn(),
  listIngressTasks: vi.fn().mockResolvedValue({ data: { tasks: [], stats: {} } }),
  getIngressTask: vi.fn().mockResolvedValue({ data: { spans: [] } }),
  cancelIngressTask: vi.fn(),
  listDeletedKnowledge: vi.fn().mockResolvedValue({ data: [] }),
  listKnowledgeConflicts: vi.fn().mockResolvedValue({ data: [] }),
  resolveKnowledgeConflict: vi.fn().mockResolvedValue({ code: 0 }),
}))

vi.mock('@/api/modules/knowledge', () => api)
vi.mock('@/api', () => ({ request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u-9', username: 'root', role: 'admin' } }),
}))
vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

const ENTRY_CONFLICT = {
  axis: 'entry', conflict_id: 'e-1', old_id: 'k-1', new_id: 'k-2', title: '同名笔记',
  similarity: 0.93, reason: '标题一致、内容相异', detected_at: 1.0, status: 'pending',
}

function factConflict(overrides: Record<string, unknown> = {}) {
  return {
    axis: 'fact', conflict_id: 'cnf_1', kind: 'value', subject_key: 'subj_1',
    subject_label: '神经瓦', predicate_term_id: 'version',
    member_fact_ids: ['fact_a', 'fact_b'],
    members_summary: ['version → 1.0', 'version → 2.0'],
    severity: 0.8, recommended_policy: 'most_recent',
    policy_basis: '按新近裁决：fact_b 晚于其余成员',
    status: 'pending', detected_at: '2026-09-20T00:00:00+00:00', ...overrides,
  }
}

/** a-select 在 jsdom 里打不开下拉，用桩件把"选中某个值"变成一次点击。 */
const SelectStub = defineComponent({
  name: 'ASelect',
  props: ['value', 'options', 'placeholder'],
  emits: ['update:value'],
  template: `<div class="select-stub"><button
    v-for="o in (options || [])" :key="o.value" class="select-opt"
    @click="$emit('update:value', o.value)">{{ o.label }}</button></div>`,
})

const stubs = {
  GlassPanel: { template: '<div class="glass-panel"><slot /></div>' },
  GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-list': {
    props: ['dataSource'],
    template: `<div class="ant-list"><template v-for="(item, i) in (dataSource || [])" :key="i">
      <slot name="renderItem" :item="item" :index="i" /></template></div>`,
  },
  'a-list-item': { template: '<div class="ant-list-item"><slot /><slot name="actions" /></div>' },
  'a-list-item-meta': {
    props: ['title', 'description'],
    template: '<div class="meta"><span class="meta-title">{{ title }}</span><span class="meta-desc">{{ description }}</span></div>',
  },
  'a-tag': { template: '<span class="tag"><slot /></span>' },
  'a-empty': { props: ['description'], template: '<div class="empty">{{ description }}</div>' },
  'a-button': { props: ['disabled', 'type', 'size'], template: '<button :disabled="disabled"><slot /></button>' },
  'a-select': SelectStub,
  ASelect: SelectStub,
}

async function mountWithConflicts(rows: unknown[]) {
  api.listKnowledgeConflicts.mockResolvedValue({ data: rows })
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
  const wrapper = mount(KnowledgePage, { global: { plugins: [i18n], stubs } })
  await flushPromises()
  return wrapper
}

/** 轴标签必须是可读文案而不是键名（键名露出来就是 i18n 断链）。 */
function queue_label(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('.kb-conflicts [data-testid="conflict-axis"]').text()
}

function queue(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('.kb-conflicts')
}

describe('知识页冲突队列 · 两条轴', () => {
  beforeEach(() => vi.clearAllMocks())

  it('默认向两侧取数（axis=all），条目侧渲染不变', async () => {
    const wrapper = await mountWithConflicts([ENTRY_CONFLICT])

    expect(api.listKnowledgeConflicts).toHaveBeenCalledWith('pending', 'all')
    expect(queue(wrapper).text()).toContain('同名笔记')
    expect(queue(wrapper).text()).toContain('93%')
  })

  it('事实侧露出种类 / 严重度 / 建议策略 / 依据', async () => {
    const wrapper = await mountWithConflicts([factConflict()])
    const text = queue(wrapper).text()

    expect(queue_label(wrapper)).toBe('治理层分歧')
    expect(text).toContain('神经瓦 · version')
    expect(text).toContain('取值分歧')
    expect(text).toContain('严重度 80%')
    expect(text).toContain('按新近')
    expect(text).toContain('按新近裁决：fact_b 晚于其余成员')
    expect(text).toContain('version → 2.0')
  })

  it('无 policy_basis 的项标红，且没有"自动裁决"入口', async () => {
    const wrapper = await mountWithConflicts([factConflict({ policy_basis: '' })])
    const panel = queue(wrapper)

    expect(panel.find('[data-testid="conflict-no-basis"]').exists()).toBe(true)
    expect(panel.text()).toContain('须人工指明胜方')
    expect(panel.text()).not.toMatch(/自动裁决|一键/)
  })

  it('未指明胜方时"新说法接管"禁用；选中胜方后才带 winner 发出', async () => {
    const wrapper = await mountWithConflicts([factConflict()])
    const buttons = wrapper.findAll('.kb-conflicts button')
    const supersede = buttons.find((b) => b.text().includes('新说法接管'))
    expect(supersede).toBeTruthy()
    expect(supersede!.attributes('disabled')).toBeDefined()

    await wrapper.findAll('.kb-conflicts .select-opt')[1].trigger('click')
    await flushPromises()
    const after = wrapper.findAll('.kb-conflicts button').find((b) => b.text().includes('新说法接管'))
    expect(after!.attributes('disabled')).toBeUndefined()
    await after!.trigger('click')
    await flushPromises()

    expect(api.resolveKnowledgeConflict).toHaveBeenCalledWith('cnf_1', 'supersede_old', 'fact_b')
  })

  it('保留双方与判为不冲突都不需要胜方', async () => {
    const wrapper = await mountWithConflicts([factConflict()])
    const dismiss = wrapper.findAll('.kb-conflicts button').find((b) => b.text().includes('判为不冲突'))
    expect(dismiss!.attributes('disabled')).toBeUndefined()

    await dismiss!.trigger('click')
    await flushPromises()

    expect(api.resolveKnowledgeConflict).toHaveBeenCalledWith('cnf_1', 'dismiss', undefined)
  })
})

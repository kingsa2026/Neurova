/**
 * 关键列表渲染回归门（追平计划 E3）—— 知识库列表
 *
 * 抽查结论（组件 → 策略 → 本文件用例）：
 * - KnowledgePage.vue（知识条目主表；条目量随导入无上限增长）：
 *   服务端分页——GET 只带 page/page_size=20，total 由后端给，onTableChange
 *   翻页重取。回归门钉住：total=800 时前端只请求/渲染当前页 20 条，翻页重取
 *   page=2 仍是有界一页。
 *   → 用例 1：首屏请求 page=1&page_size=20，表格只渲染 20 行，pagination.total=800；
 *   → 用例 2：表格 change 事件翻到第 2 页 → 重发 page=2 请求，渲染仍 20 行。
 * - 同域登记：GraphWorkbenchPage.vue 图谱社群列表以 slice(0, 5) 截断（有界）；
 *   ChatSessionSidebar.vue 会话列表为无界渲染（已登记未修）。
 *
 * 门径：谁把 page_size 改成全量、或丢掉服务端分页改整表直挂，本文件即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h } from 'vue'
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
  listKnowledgeCategories: vi.fn().mockResolvedValue({ data: [] }),
  listKnowledgeRevisions: vi.fn().mockResolvedValue({ data: [] }),
  syncKbConfig: vi.fn().mockResolvedValue({ data: { upserted: 0, deleted: 0, failed: 0 } }),
  listResolutionReviews: vi.fn().mockResolvedValue({ data: [] }),
  resolveResolutionReview: vi.fn(),
  runEntityResolution: vi.fn(),
  listMcpSources: vi.fn().mockResolvedValue({ data: { items: [] } }),
  probeMcpTools: vi.fn().mockResolvedValue({ data: { tools: [] } }),
  createMcpSource: vi.fn(),
  updateMcpSource: vi.fn(),
  pullMcpSource: vi.fn(),
  deleteMcpSource: vi.fn(),
  importKnowledgeFile: vi.fn(),
  importKnowledgeFromUrl: vi.fn(),
}))

vi.mock('@/api/modules/knowledge', () => api)
vi.mock('@/api/modules/ontology', () => ({
  listChunkStrategies: vi.fn().mockResolvedValue({ data: [] }),
  searchCommunityGraph: vi.fn().mockResolvedValue({ data: {} }),
  getOntologyBlockingStats: vi.fn().mockResolvedValue({ data: {} }),
  getOntologyConflictPolicy: vi.fn().mockResolvedValue({ data: {} }),
}))
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

const PAGE_SIZE = 20
const TOTAL = 800

function makeItems(page: number) {
  return Array.from({ length: PAGE_SIZE }, (_, i) => ({
    id: `kb-${page}-${i}`,
    knowledge_id: `kb-${page}-${i}`,
    title: `知识条目 ${page}-${i}`,
    category: 'tech',
    content: `内容 ${page}-${i}`,
    visibility: 'private',
    owner_user_id: 'u-9',
    chunk_count: 1,
    sources: [],
    created_at: '2026-11-01 00:00:00',
    source_modified_at: '2026-11-01 00:00:00',
  }))
}

/** a-table 桩：按 dataSource 逐行渲染（可数 DOM），并透传 pagination 供断言。 */
const ATableStub = defineComponent({
  name: 'KbTableStub',
  props: ['columns', 'dataSource', 'pagination', 'loading', 'rowSelection', 'rowKey', 'locale'],
  emits: ['change'],
  setup(props) {
    return () =>
      h(
        'div',
        { class: 'kb-table-stub', 'data-pag': JSON.stringify(props.pagination ?? null) },
        (props.dataSource ?? []).map((r: any) =>
          h('div', { class: 'kb-row', 'data-id': r.id }, r.title),
        ),
      )
  },
})

const passthrough = { template: '<div><slot /></div>' }
const stubs = {
  ATable: ATableStub,
  'a-table': ATableStub,
  GlassPanel: passthrough,
  GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="ant-modal"><slot /></div>' },
  'a-list': passthrough,
  'a-list-item': passthrough,
  'a-list-item-meta': passthrough,
  'a-badge': passthrough,
  'a-button': passthrough,
  'a-checkbox': passthrough,
  'a-date-picker': passthrough,
  'a-divider': passthrough,
  'a-drawer': passthrough,
  'a-empty': passthrough,
  'a-form': passthrough,
  'a-form-item': passthrough,
  'a-input': passthrough,
  'a-input-number': passthrough,
  'a-input-password': passthrough,
  'a-input-search': passthrough,
  'a-popconfirm': passthrough,
  'a-popover': passthrough,
  'a-radio-button': passthrough,
  'a-radio-group': passthrough,
  'a-select': passthrough,
  'a-select-option': passthrough,
  'a-space': passthrough,
  'a-spin': passthrough,
  'a-switch': passthrough,
  'a-tag': passthrough,
  'a-textarea': passthrough,
  'a-timeline': passthrough,
  'a-timeline-item': passthrough,
  'a-upload': passthrough,
  'a-upload-dragger': passthrough,
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })
  return mount(KnowledgePage, { global: { plugins: [i18n], stubs } })
}

describe('KnowledgePage 关键列表渲染回归门（服务端分页不退化为整表渲染）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getKnowledgeNodes.mockResolvedValue({ data: { items: makeItems(1), total: TOTAL } })
  })

  it('总量 800：首屏只请求/渲染一页 20 条，pagination 标称全量', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(api.getKnowledgeNodes).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: PAGE_SIZE }),
    )

    const rows = wrapper.findAll('.kb-row')
    expect(rows.length, `total=${TOTAL} 时表格只应渲染当前页 ${PAGE_SIZE} 行`).toBe(PAGE_SIZE)

    const pag = JSON.parse(wrapper.find('.kb-table-stub').attributes('data-pag') ?? 'null')
    expect(pag?.total, 'pagination 须携带服务端全量 total').toBe(TOTAL)
    expect(pag?.pageSize).toBe(PAGE_SIZE)

    wrapper.unmount()
  })

  it('翻页（table change）重取 page=2，渲染仍是有界一页', async () => {
    const wrapper = mountPage()
    await flushPromises()

    api.getKnowledgeNodes.mockClear()
    api.getKnowledgeNodes.mockResolvedValue({ data: { items: makeItems(2), total: TOTAL } })

    const stub = wrapper.findComponent(ATableStub)
    expect(stub.exists(), '主表须挂载').toBe(true)
    ;(stub.vm as any).$emit('change', { current: 2, pageSize: PAGE_SIZE })
    await flushPromises()

    expect(api.getKnowledgeNodes).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, page_size: PAGE_SIZE }),
    )
    const rows = wrapper.findAll('.kb-row')
    expect(rows.length, '翻页后仍只渲染一页 20 行').toBe(PAGE_SIZE)
    expect(rows[0].attributes('data-id'), '翻页后应渲染第 2 页数据').toBe('kb-2-0')

    wrapper.unmount()
  })
})

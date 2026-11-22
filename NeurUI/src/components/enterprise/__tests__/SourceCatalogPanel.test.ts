/**
 * SourceCatalogPanel — 企业源目录面板契约测试（U10 列画像 + 目录主视图配套批）。
 *
 * 契约面（自 SourceCatalogDrawer 抽屉内容提取为内联面板，交互不缩水）：
 * - 挂载即按 sourceId 拉目录；源切换（prop 变更）重新拉取并重置搜索词；
 * - 搜索（回车）按当前源 + 关键词拉取；
 * - 手动刷新走 refreshSourceCatalog，仅管理员可见；
 * - 列明细（U10）：distinct 数 / null 率 / min / max / 样例值（≤5）/ 采样行数，
 *   sample_rows=0/NULL 时这些画像列显式显「未采样」，不冒充 0 值；
 * - PK/FK 标签与采样态无关，照常渲染。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/ontology', () => ({
  listCatalogTables: vi.fn(),
  getCatalogTableDetail: vi.fn(),
  refreshSourceCatalog: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import SourceCatalogPanel from '@/components/enterprise/SourceCatalogPanel.vue'
import {
  listCatalogTables,
  getCatalogTableDetail,
  refreshSourceCatalog,
} from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const listMock = listCatalogTables as unknown as ReturnType<typeof vi.fn>
const detailMock = getCatalogTableDetail as unknown as ReturnType<typeof vi.fn>
const refreshMock = refreshSourceCatalog as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
    },
  },
})

/** a-table stub：按 columns 逐列渲染 bodyCell，让画像列/键标签断言可逐格落点 */
const tableStub = {
  props: ['dataSource', 'columns'],
  template: `<div class="stub-table">
    <div v-for="row in dataSource || []" :key="row.catalog_column_id || row.catalog_table_id" class="stub-row">
      <span v-for="col in columns || []" :key="col.key" :class="'cell-' + col.key">
        <slot name="bodyCell" :column="col" :record="row" />
      </span>
    </div>
  </div>`,
}

const stubs = {
  'a-table': tableStub,
  'a-spin': { props: ['spinning'], template: '<div class="stub-spin"><slot /></div>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot /></div>' },
  'a-input': {
    props: ['value', 'disabled', 'placeholder', 'size'],
    emits: ['update:value', 'pressEnter'],
    template: `<input class="stub-input" :value="value" :placeholder="placeholder" :disabled="disabled"
      @input="$emit('update:value', $event.target.value)" @keydown.enter="$emit('pressEnter')" />`,
  },
  GlassButton: {
    props: ['loading', 'disabled', 'variant', 'size'],
    emits: ['click'],
    template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
}

const mountPanel = (props: { sourceId: string; isAdmin: boolean } = { sourceId: 'src_a', isAdmin: true }) =>
  mount(SourceCatalogPanel, {
    global: { plugins: [i18n], stubs },
    props,
    attachTo: document.body,
  })

function tableRow(overrides: Record<string, unknown> = {}) {
  return {
    catalog_table_id: 't1',
    tenant_id: 'default',
    source_id: 'src_a',
    source_type: 'sql',
    table_name: 'orders',
    table_type: 'table',
    description: '',
    term_id: '',
    column_count: 2,
    ingested_at: '2026-11-23T10:00:00',
    ...overrides,
  }
}

function columnRow(overrides: Record<string, unknown> = {}) {
  return {
    catalog_column_id: 'c1',
    column_name: 'order_id',
    data_type: 'bigint',
    ordinal_position: 0,
    is_primary_key: 1,
    is_foreign_key: 0,
    foreign_key_target: '',
    description: '',
    term_id: '',
    profile_distinct: 4,
    profile_null_rate: 0.25,
    profile_min: '1001',
    profile_max: '1004',
    profile_samples_json: '["1001","1002","1003","1004"]',
    profile_sample_rows: 100,
    ...overrides,
  }
}

beforeEach(() => {
  listMock.mockReset()
  listMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [], total: 0 } })
  detailMock.mockReset()
  detailMock.mockResolvedValue({ code: 0, message: 'ok', data: { columns: [] } })
  refreshMock.mockReset()
  refreshMock.mockResolvedValue({
    code: 0, message: 'ok',
    data: { source_id: 'src_a', ingested: { tables: 1, columns: 2, foreign_keys: 0 } },
  })
})

describe('SourceCatalogPanel（目录加载与源切换）', () => {
  it('挂载即按 sourceId 拉取目录清单', async () => {
    mountPanel()
    await flushPromises()
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(listMock).toHaveBeenCalledWith('src_a', '')
  })

  it('sourceId 缺省为空时不发目录请求', async () => {
    mountPanel({ sourceId: '', isAdmin: true })
    await flushPromises()
    expect(listMock).not.toHaveBeenCalled()
  })

  it('源切换触发重新加载，并重置搜索词与已开明细', async () => {
    listMock.mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [tableRow()], total: 1 },
    })
    detailMock.mockResolvedValue({ code: 0, message: 'ok', data: { columns: [columnRow()] } })
    const wrapper = mountPanel()
    await flushPromises()

    // 搜索词 + 打开列明细
    await wrapper.find('[data-testid="catalog-search"]').setValue('order')
    await wrapper.find('[data-testid="catalog-detail-btn"]').trigger('click')
    await flushPromises()
    expect(detailMock).toHaveBeenCalledWith('t1')

    listMock.mockClear()
    await wrapper.setProps({ sourceId: 'src_b' })
    await flushPromises()
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(listMock).toHaveBeenCalledWith('src_b', '')
    // 搜索词被重置（抽屉 destroy-on-close 的等价语义：换源=新目录面）
    expect((wrapper.find('[data-testid="catalog-search"]').element as HTMLInputElement).value).toBe('')
    // 已开的列明细随换源关闭（不同源同名表不可冒充）
    expect(wrapper.find('.stub-modal').exists()).toBe(false)
  })

  it('搜索回车：按当前源 + 关键词拉取', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    listMock.mockClear()
    await wrapper.find('[data-testid="catalog-search"]').setValue('order')
    await wrapper.find('[data-testid="catalog-search"]').trigger('keydown.enter')
    await flushPromises()
    expect(listMock).toHaveBeenCalledWith('src_a', 'order')
  })

  it('手动刷新：走 refreshSourceCatalog 并重拉目录（仅管理员可见）', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.find('[data-testid="catalog-refresh"]').exists()).toBe(true)
    listMock.mockClear()
    await wrapper.find('[data-testid="catalog-refresh"]').trigger('click')
    await flushPromises()
    expect(refreshMock).toHaveBeenCalledWith('src_a')
    expect(listMock).toHaveBeenCalledTimes(1)

    const nonAdmin = mountPanel({ sourceId: 'src_a', isAdmin: false })
    await flushPromises()
    expect(nonAdmin.find('[data-testid="catalog-refresh"]').exists()).toBe(false)
  })
})

describe('SourceCatalogPanel（U10 列画像）', () => {
  beforeEach(() => {
    listMock.mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [tableRow()], total: 1 },
    })
  })

  const openDetail = async () => {
    detailMock.mockResolvedValue({
      code: 0, message: 'ok',
      data: {
        columns: [
          columnRow(),
          columnRow({
            catalog_column_id: 'c2',
            column_name: 'customer_id',
            is_primary_key: 0,
            is_foreign_key: 1,
            foreign_key_target: 'customers.customer_id',
            profile_distinct: null,
            profile_null_rate: null,
            profile_min: null,
            profile_max: null,
            profile_samples_json: '[]',
            profile_sample_rows: 0,
          }),
        ],
      },
    })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="catalog-detail-btn"]').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('已采样列：distinct/null 率/min/max/样例/采样行数如实渲染', async () => {
    const wrapper = await openDetail()
    expect(wrapper.find('.stub-modal').exists()).toBe(true)
    expect(wrapper.find('.stub-modal .cell-profile_distinct').text()).toBe('4')
    expect(wrapper.find('.stub-modal .cell-profile_null_rate').text()).toBe('25.00%')
    expect(wrapper.find('.stub-modal .cell-profile_min').text()).toBe('1001')
    expect(wrapper.find('.stub-modal .cell-profile_max').text()).toBe('1004')
    expect(wrapper.find('.stub-modal .cell-profile_samples').text()).toBe('1001, 1002, 1003, 1004')
    expect(wrapper.find('.stub-modal .cell-profile_sample_rows').text()).toBe('100')
    // 画像列不出现「未采样」占位
    expect(wrapper.find('.stub-modal .cell-profile_distinct.profile-unsampled').exists()).toBe(false)
  })

  it('未采样列（sample_rows=0/NULL）：画像列显式显「未采样」，不冒充 0 值', async () => {
    const wrapper = await openDetail()
    // 行选择域限定在列明细弹层（表清单表格的行也用 .stub-row）
    const unsampled = wrapper.findAll('.stub-modal .stub-row')[1]
    expect(unsampled.find('.cell-profile_distinct').text()).toContain('未采样')
    expect(unsampled.find('.cell-profile_null_rate').text()).toContain('未采样')
    expect(unsampled.find('.cell-profile_min').text()).toContain('未采样')
    expect(unsampled.find('.cell-profile_max').text()).toContain('未采样')
    expect(unsampled.find('.cell-profile_samples').text()).toContain('未采样')
    expect(unsampled.find('.cell-profile_sample_rows').text()).toContain('未采样')
  })

  it('样例值最多展示 5 个（后端 ≤5 约定的前端兜底）', async () => {
    detailMock.mockResolvedValue({
      code: 0, message: 'ok',
      data: {
        columns: [columnRow({
          profile_samples_json: '["a","b","c","d","e","f"]',
        })],
      },
    })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="catalog-detail-btn"]').trigger('click')
    await flushPromises()
    const samples = wrapper.find('.stub-modal .cell-profile_samples').text()
    expect(samples).toBe('a, b, c, d, e')
    expect(samples).not.toContain('f')
  })

  it('PK/FK 标签照常渲染，与采样态无关', async () => {
    const wrapper = await openDetail()
    const rows = wrapper.findAll('.stub-modal .stub-row')
    expect(rows[0].find('[data-testid="catalog-pk-tag"]').text()).toContain('主键')
    expect(rows[0].find('[data-testid="catalog-fk-tag"]').exists()).toBe(false)
    expect(rows[1].find('[data-testid="catalog-fk-tag"]').text()).toContain('外键')
    expect(rows[1].find('[data-testid="catalog-fk-tag"]').text()).toContain('customers.customer_id')
    expect(rows[1].find('[data-testid="catalog-pk-tag"]').exists()).toBe(false)
  })

  it('画像损坏（samples_json 非法 JSON）按空样例处理，不炸面板', async () => {
    detailMock.mockResolvedValue({
      code: 0, message: 'ok',
      data: { columns: [columnRow({ profile_samples_json: 'not-json' })] },
    })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="catalog-detail-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.stub-modal .cell-profile_samples').text()).toBe('—')
  })
})

/**
 * 企业源同步历史「触发来源」列 i18n 标签映射测试。
 *
 * 背景（车道C）：trigger_kind 新增 startup/audit 取值（既有 manual/interval），
 * 同步历史抽屉该列此前为原值直出——新值会以英文原样显示给中文用户。
 *
 * 契约：
 * - manual/interval/startup/audit → ontology 节 4 个新键的 zh-CN 标签；
 * - 未知值兜底回退原值直出（诚实，不猜）；
 * - 4 个新键在全部 11 个语言包中存在且非空（防单语补键、其余静默回退）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { h, type Slots, type VNode } from 'vue'

const authUser = { id: 'u1', username: 'tester', role: 'admin' }
;(globalThis as Record<string, unknown>).__enterpriseSourcesAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__enterpriseSourcesAuthUser
    },
  }),
}))

vi.mock('@/api/modules/ontology', () => ({
  listEnterpriseSources: vi.fn(),
  submitEnterpriseSource: vi.fn(),
  triggerEnterpriseIngest: vi.fn(),
  getEnterpriseSourceHealth: vi.fn(),
  deleteEnterpriseSource: vi.fn(),
  triggerEnterpriseMedia: vi.fn(),
  getEnterpriseSyncHistory: vi.fn(),
  getEnterpriseSyncInterval: vi.fn(),
  updateEnterpriseSyncInterval: vi.fn(),
  getEnterpriseShareTenants: vi.fn(),
  updateEnterpriseShareTenants: vi.fn(),
  getWebhookConfig: vi.fn(),
  rotateWebhookSecret: vi.fn(),
  simulateWebhookPush: vi.fn(),
  getWebhookDedupStats: vi.fn(),
  listCatalogTables: vi.fn(),
  getCatalogTableDetail: vi.fn(),
  refreshSourceCatalog: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import EnterpriseSourcesPage from '@/pages/EnterpriseSourcesPage.vue'
import { listEnterpriseSources, getEnterpriseSyncHistory, listCatalogTables } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import frFR from '@/i18n/locales/fr-FR'
import deDE from '@/i18n/locales/de-DE'
import esES from '@/i18n/locales/es-ES'
import itIT from '@/i18n/locales/it-IT'
import ruRU from '@/i18n/locales/ru-RU'
import arSA from '@/i18n/locales/ar-SA'
import hiIN from '@/i18n/locales/hi-IN'

const listMock = listEnterpriseSources as unknown as ReturnType<typeof vi.fn>
const historyMock = getEnterpriseSyncHistory as unknown as ReturnType<typeof vi.fn>
const catalogListMock = listCatalogTables as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { edit: '编辑', delete: '删除', save: '保存', error: '操作失败', success: '成功' },
    },
  },
})

/**
 * a-table stub：既渲染主列表的 bodyCell 行内插槽，也渲染同步历史抽屉的
 * a-table-column 子列（按 data-index 取行值、把作用域插槽 { text, record } 展开成单元格）。
 */
const tableStub = {
  props: ['dataSource', 'loading', 'columns', 'pagination', 'rowKey', 'size'],
  setup(props: { dataSource?: Array<Record<string, unknown>> }, { slots }: { slots: Slots }) {
    return () => {
      const rows = props.dataSource || []
      // a-table-column 经运行时解析，vnode props 保留 kebab-case 的 data-index
      const dataIndexOf = (v: VNode) => (v.props?.dataIndex ?? v.props?.['data-index']) as string | undefined
      const columnVnodes = ((slots.default?.() ?? []) as VNode[]).filter(
        (v) => v && v.props && dataIndexOf(v) !== undefined,
      )
      if (columnVnodes.length) {
        return h(
          'div',
          { class: 'stub-history-table' },
          rows.map((row) =>
            h(
              'div',
              { class: 'stub-history-row' },
              columnVnodes.map((col) => {
                const dataIndex = String(dataIndexOf(col))
                const slotFn = (col.children as unknown as { default?: (scope: { text: unknown; record: unknown }) => VNode[] } | null | undefined)?.default
                const content = slotFn
                  ? slotFn({ text: row[dataIndex], record: row })
                  : String(row[dataIndex] ?? '')
                return h('div', { class: `cell-${dataIndex}` }, content)
              }),
            ),
          ),
        )
      }
      return h(
        'div',
        { class: 'stub-table' },
        rows.map((row) =>
          h(
            'div',
            { class: 'stub-row' },
            slots.bodyCell?.({ column: { key: 'actions' }, record: row }) ?? [],
          ),
        ),
      )
    }
  },
}

const stubs = {
  'a-table': tableStub,
  'a-table-column': { props: ['title', 'dataIndex', 'width'], template: '<div class="stub-col"><slot /></div>' },
  'a-drawer': { props: ['open', 'title'], template: '<div v-if="open" class="stub-drawer"><slot /></div>' },
  'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="stub-badge">{{ text }}</span>' },
  'a-switch': { props: ['checked', 'disabled', 'size'], emits: ['change'], template: '<button class="stub-switch" @click="$emit(\'change\', !checked)" />' },
  'a-popconfirm': { props: ['title'], template: '<span class="stub-pop"><slot /></span>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot /><slot name="footer" /></div>' },
  'a-steps': { props: ['current'], template: '<div class="stub-steps"><slot /></div>' },
  'a-step': { props: ['title'], template: '<div class="stub-step">{{ title }}</div>' },
  'a-form': { template: '<form class="stub-form"><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<label class="stub-form-item"><slot /></label>' },
  'a-input': { props: ['value', 'disabled', 'placeholder'], emits: ['update:value'], template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], emits: ['update:value'], template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-select': { props: ['value', 'options', 'placeholder'], emits: ['update:value'], template: '<select class="stub-select" :value="value"><option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-divider': { template: '<div class="stub-divider"><slot /></div>' },
  GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
  GlassButton: {
    props: ['loading', 'disabled', 'variant'],
    emits: ['click'],
    template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
}

const mountPage = () =>
  mount(EnterpriseSourcesPage, {
    global: { plugins: [i18n], stubs },
    attachTo: document.body,
  })

function sourceRow() {
  return {
    source_id: 'erp_orders',
    descriptor: { sourceType: 'sql', columns: ['order_id'] },
    cursor: '',
    enabled: false,
    adapter_registered: false,
    created_at: '2026-11-20T10:00:00',
    updated_at: '2026-11-20T10:00:00',
    ingested_count: 7,
  }
}

function historyRow(triggerKind: string, startedAt: string) {
  return {
    started_at: startedAt,
    finished_at: startedAt,
    trigger_kind: triggerKind,
    status: 'ok',
    reason: '',
    batches: 1,
    admitted: 3,
    rejected: 0,
    rows_skipped: 0,
    entries_written: 3,
    truncated: false,
    cursor_before: '',
    cursor_after: '',
    duration_ms: 12,
  }
}

beforeEach(() => {
  listMock.mockReset()
  listMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [sourceRow()], total: 1 } })
  historyMock.mockReset()
  historyMock.mockResolvedValue({ code: 0, message: 'ok', data: { source_id: 'erp_orders', items: [] } })
  catalogListMock.mockReset()
  catalogListMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [], total: 0 } })
  authUser.role = 'admin'
})

/** 打开同步历史抽屉并注入指定 trigger_kind 的历史行 */
async function openHistoryWith(triggerKinds: string[]) {
  historyMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      source_id: 'erp_orders',
      items: triggerKinds.map((kind, i) => historyRow(kind, `2026-11-20T0${i}:00:00`)),
    },
  })
  const wrapper = mountPage()
  await flushPromises()
  await wrapper.find('[data-testid="ent-history-btn"]').trigger('click')
  await flushPromises()
  return wrapper
}

describe('EnterpriseSourcesPage 同步历史触发来源 i18n', () => {
  it('manual/interval/startup/audit 渲染 zh-CN 标签而非原值直出', async () => {
    const wrapper = await openHistoryWith(['manual', 'interval', 'startup', 'audit'])
    const cells = wrapper.findAll('.stub-history-row .cell-trigger_kind')
    expect(cells.map((c) => c.text())).toEqual(['手动', '定时', '启动', '审计'])
  })

  it('未知 trigger_kind 兜底回退原值直出（不猜标签）', async () => {
    const wrapper = await openHistoryWith(['legacy_kind'])
    const cell = wrapper.find('.stub-history-row .cell-trigger_kind')
    expect(cell.exists()).toBe(true)
    expect(cell.text()).toBe('legacy_kind')
  })

  it('4 个触发来源键在全部 11 个语言包中存在且非空', () => {
    const packs: Record<string, Record<string, unknown>> = {
      'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR, 'fr-FR': frFR,
      'de-DE': deDE, 'es-ES': esES, 'it-IT': itIT, 'ru-RU': ruRU, 'ar-SA': arSA, 'hi-IN': hiIN,
    }
    const keys = ['entTriggerManual', 'entTriggerInterval', 'entTriggerStartup', 'entTriggerAudit']
    for (const [code, pack] of Object.entries(packs)) {
      const ontology = (pack.ontology ?? {}) as Record<string, unknown>
      for (const key of keys) {
        const value = ontology[key]
        expect([code, key, typeof value === 'string' && value.length > 0]).toEqual([code, key, true])
      }
    }
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * P1-26（审计 2026-11-16）：EnterpriseSourcesPage webhook 抽屉不可达——
 * :411-449 抽屉、openWebhookDrawer 逻辑俱在，但操作列无任何入口置
 * webhookDrawerOpen = true，U5 webhook 接收面（密钥指纹/轮换/模拟推送/幂等
 * 去重读数）对用户完全不可达。按拍板「能接线先接线」：操作列补「Webhook」入口。
 */
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
  getWebhookConfig: vi.fn(),
  rotateWebhookSecret: vi.fn(),
  simulateWebhookPush: vi.fn(),
  getWebhookDedupStats: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import EnterpriseSourcesPage from '@/pages/EnterpriseSourcesPage.vue'
import { listEnterpriseSources, getWebhookConfig, getWebhookDedupStats } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const listMock = listEnterpriseSources as unknown as ReturnType<typeof vi.fn>
const webhookConfigMock = getWebhookConfig as unknown as ReturnType<typeof vi.fn>
const dedupMock = getWebhookDedupStats as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { edit: '编辑', delete: '删除', save: '保存', error: '操作失败', success: '成功', yes: '是', no: '否' },
    },
  },
})

const tableStub = {
  props: ['dataSource'],
  template: `<div class="stub-table">
    <div v-for="row in dataSource || []" :key="row.source_id" class="stub-row">
      <span class="cell-actions"><slot name="bodyCell" :column="{ key: 'actions' }" :record="row" /></span>
    </div>
  </div>`,
}

const stubs = {
  'a-table': tableStub,
  'a-drawer': { props: ['open', 'title'], template: '<div v-if="open" class="stub-drawer" :data-title="title"><slot /></div>' },
  'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="stub-badge" :data-status="status">{{ text }}</span>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot /><slot name="footer" /></div>' },
  'a-divider': { template: '<div class="stub-divider"><slot /></div>' },
  'a-input': { props: ['value', 'disabled', 'placeholder'], emits: ['update:value'], template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], emits: ['update:value'], template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-select': { props: ['value', 'options', 'placeholder'], emits: ['update:value'], template: '<select class="stub-select" :value="value"><option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-steps': { props: ['current'], template: '<div class="stub-steps"><slot /></div>' },
  'a-step': { props: ['title'], template: '<div class="stub-step">{{ title }}</div>' },
  'a-form': { template: '<form class="stub-form"><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<label class="stub-form-item"><slot /></label>' },
  'a-switch': { props: ['checked', 'disabled'], emits: ['change'], template: '<button class="stub-switch" @click="$emit(\'change\', !checked)" />' },
  'a-popconfirm': { props: ['title'], template: '<span class="stub-pop"><button class="pop-confirm-btn" @click="$emit(\'confirm\')"><slot /></button></span>' },
  'a-row': { template: '<div><slot /></div>' },
  'a-col': { template: '<div><slot /></div>' },
  GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
  GlassButton: {
    props: ['loading', 'disabled', 'variant'],
    emits: ['click'],
    template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
  SourceCatalogDrawer: { template: '<div />' },
  SourceNl2SqlDrawer: { template: '<div />' },
}

function sourceRow(overrides: Record<string, unknown> = {}) {
  return {
    source_id: 'erp_orders',
    descriptor: { sourceType: 'sql', columns: ['order_id'] },
    cursor: '',
    enabled: false,
    adapter_registered: false,
    created_at: '2026-11-07T10:00:00',
    updated_at: '2026-11-07T10:00:00',
    ingested_count: 7,
    ...overrides,
  }
}

function mountPage() {
  return mount(EnterpriseSourcesPage, {
    global: { plugins: [i18n], stubs },
    attachTo: document.body,
  })
}

beforeEach(() => {
  listMock.mockReset().mockResolvedValue({
    code: 0, message: 'ok', data: { items: [sourceRow()], total: 1 },
  })
  webhookConfigMock.mockReset().mockResolvedValue({
    code: 0, message: 'ok', data: { enabled: true, secret_env: 'NEUROVA_WEBHOOK_SECRET', secret_fingerprint: 'sha256:abc123' },
  })
  dedupMock.mockReset().mockResolvedValue({
    code: 0, message: 'ok', data: { rows: 12, sources: 3 },
  })
})

describe('EnterpriseSourcesPage — webhook 抽屉入口接线（P1-26）', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('操作列渲染「Webhook」入口，点击打开抽屉并拉取配置/去重读数（修复前：抽屉不可达）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const row = wrapper.find('.stub-row')
    expect(row.exists()).toBe(true)

    const webhookBtn = row.findAll('button').find((b) => (b.text() || '').includes('Webhook'))
    expect(webhookBtn, '操作列应有「Webhook」入口（openWebhookDrawer 此前零调用）').toBeTruthy()

    await webhookBtn!.trigger('click')
    await flushPromises()

    expect(webhookConfigMock).toHaveBeenCalled()
    expect(dedupMock).toHaveBeenCalled()
    const drawer = wrapper.find('.stub-drawer')
    expect(drawer.exists(), 'webhook 抽屉应渲染').toBe(true)
    expect(drawer.text()).toContain('sha256:abc123')
    expect(drawer.text()).toContain('模拟推送')
  })
})

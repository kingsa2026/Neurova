/**
 * EnterpriseSourcesPage — UI-4 企业数据源契约测试。
 *
 * 契约面（§15.4 企业源不伪装）：
 * - 页面显式显示「接口预留／未接入真实源」标记与说明；
 * - 源列表走真 REST：空态说明是诚实状态（不是故障），有行时逐行回显
 *   enabled 与 adapter_registered 两态——「描述符落库」不等于「源已接通」；
 * - 描述符编辑器提交是真调用，body 形状与后端 validateDescriptor 对齐；
 *   400 的拒因原样露出，不降级成 warning；
 * - 非管理员提交按钮禁用（治理门在后端，前端不假装能写）；
 * - 「连接/同步」按钮禁用并给出原因（真实连接器另立项）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
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
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import EnterpriseSourcesPage from '@/pages/EnterpriseSourcesPage.vue'
import { listEnterpriseSources, submitEnterpriseSource } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const listMock = listEnterpriseSources as unknown as ReturnType<typeof vi.fn>
const submitMock = submitEnterpriseSource as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { required: '此项必填', error: '操作失败' },
    },
  },
})

const mountPage = () =>
  mount(EnterpriseSourcesPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-select': {
          props: ['value'],
          emits: ['update:value'],
          template: '<select class="stub-select" :value="value" @change="$emit(\'update:value\', $event.target.value)"><slot /></select>',
        },
        'a-select-option': { props: ['value'], template: '<option :value="value"><slot /></option>' },
        'a-checkbox': {
          props: ['checked', 'disabled'],
          emits: ['update:checked'],
          template: '<input type="checkbox" class="stub-check" :checked="checked" :disabled="disabled" @change="$emit(\'update:checked\', $event.target.checked)" />',
        },
        'a-tooltip': { props: ['title'], template: '<div class="stub-tooltip" :data-reason="title"><slot /></div>' },
        GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
        GlassButton: {
          props: ['loading', 'disabled', 'variant'],
          emits: ['click'],
          template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })

function sourceRow(overrides: Record<string, unknown> = {}) {
  return {
    source_id: 'erp_orders',
    descriptor: { sourceType: 'sql', columns: ['order_id'] },
    cursor: '',
    enabled: false,
    adapter_registered: false,
    ...overrides,
  }
}

beforeEach(() => {
  listMock.mockReset()
  listMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [], total: 0 } })
  submitMock.mockReset()
  submitMock.mockResolvedValue({ code: 0, message: 'ok', data: sourceRow() })
  authUser.role = 'admin'
})

describe('EnterpriseSourcesPage（UI-4）', () => {
  it('空态渲染：显式「接口预留」标记、源列表空态说明为诚实状态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="ent-reserved-tag"]').text()).toContain('接口预留')
    expect(wrapper.find('[data-testid="ent-list-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="ent-list-empty"]').text()).toContain('诚实状态')
    // fake adapter 只存在于服务端测试路径——页面不提供演示按钮
    expect(wrapper.text()).toContain('tests/unit/knowledge/enterprise/')
    expect(wrapper.find('button').text()).not.toContain('演示')
  })

  it('列表态：逐行回显 enabled 与 adapter_registered（配置落库 ≠ 源已接通）', async () => {
    listMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { items: [sourceRow()], total: 1 },
    })
    const wrapper = mountPage()
    await flushPromises()
    const row = wrapper.find('[data-testid="ent-row-erp_orders"]')
    expect(row.exists()).toBe(true)
    expect(row.find('[data-testid="ent-enabled-tag"]').text()).toBe('off')
    expect(row.find('[data-testid="ent-adapter-tag"]').text()).toContain('适配器未注册')
  })

  it('描述符提交：body 与后端编译期校验形状对齐，成功后重读列表', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-source-id"]').setValue('erp_orders')
    await wrapper.find('[data-testid="ent-columns"]').setValue('order_id, risk_level')
    await wrapper.find('[data-testid="ent-subject"]').setValue('orders:{order_id}')
    await wrapper.find('[data-testid="ent-predicate"]').setValue('hasRiskLevel')
    await wrapper.find('[data-testid="ent-object-value"]').setValue('risk_level')
    await wrapper.find('[data-testid="ent-submit"]').trigger('click')
    await flushPromises()

    expect(submitMock).toHaveBeenCalledTimes(1)
    expect(submitMock.mock.calls[0][0]).toEqual({
      source_id: 'erp_orders',
      enabled: false,
      descriptor: {
        sourceType: 'sql',
        columns: ['order_id', 'risk_level'],
        subject: { template: 'orders:{order_id}' },
        predicate: { termId: 'hasRiskLevel' },
        object: { kind: 'column', column: 'risk_level' },
        qualifiers: {},
      },
    })
    // 提交后重读：列表读数来自服务端，不是前端自增一行
    expect(listMock).toHaveBeenCalledTimes(2)
  })

  it('拒因显式：400 的 detail 原样露出，不降级成「操作失败」了事', async () => {
    submitMock.mockRejectedValue({
      response: { data: { detail: "predicate not_registered 未登记（先登记术语再配映射）" } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-source-id"]').setValue('erp_bad')
    await wrapper.find('[data-testid="ent-predicate"]').setValue('not_registered')
    await wrapper.find('[data-testid="ent-submit"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="ent-submit-error"]').text()).toContain('未登记')
  })

  it('权限态：非管理员提交按钮与启用勾选禁用，并给出管理员限定说明', async () => {
    authUser.role = 'user'
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="ent-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="ent-enabled"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="ent-admin-note"]').text()).toContain('仅管理员')
  })

  it('连接态诚实：连接按钮禁用并给出「另立项」原因', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const connect = wrapper.find('[data-testid="ent-connect-disabled"]')
    expect(connect.exists()).toBe(true)
    expect(connect.attributes('disabled')).toBeDefined()
    const tooltip = wrapper.find('.stub-tooltip')
    expect(tooltip.attributes('data-reason')).toContain('另立项')
  })
})

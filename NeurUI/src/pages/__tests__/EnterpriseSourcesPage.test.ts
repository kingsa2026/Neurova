/**
 * EnterpriseSourcesPage — 页面重设计契约测试（连接器列表＋四步向导）。
 *
 * 契约面（§15.4 企业源不伪装 + 页面重设计配套批）：
 * - 列表行回显：类型中文标签（sql→数据库、chat+wecom→企微）、添加时间、已获取计数；
 * - 行内"检测"走真 health 端点，三态徽标如实（未检测/正常/受限/异常）；
 * - 向导四步：步 0 选型守门、步 1 逐类型必填（sql→driver/database/cursorColumn/table|query）、
 *   步 2 映射必填、保存 body 与后端 validateDescriptor 对齐（object.column 键）；
 * - 编辑预填：kind 从描述符反推（chat+wecom→企微卡）、source_id 锁定、vendor 保持；
 * - 删除确认点名"已获取数据保留"，走真 DELETE 端点；
 * - 启用开关翻转走 POST upsert；逐行摄取四数如实报、skipped 走 info。
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
  triggerEnterpriseIngest: vi.fn(),
  getEnterpriseSourceHealth: vi.fn(),
  deleteEnterpriseSource: vi.fn(),
  triggerEnterpriseMedia: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import EnterpriseSourcesPage from '@/pages/EnterpriseSourcesPage.vue'
import {
  listEnterpriseSources,
  submitEnterpriseSource,
  triggerEnterpriseIngest,
  getEnterpriseSourceHealth,
  deleteEnterpriseSource,
  triggerEnterpriseMedia,
} from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const listMock = listEnterpriseSources as unknown as ReturnType<typeof vi.fn>
const submitMock = submitEnterpriseSource as unknown as ReturnType<typeof vi.fn>
const ingestMock = triggerEnterpriseIngest as unknown as ReturnType<typeof vi.fn>
const healthMock = getEnterpriseSourceHealth as unknown as ReturnType<typeof vi.fn>
const deleteMock = deleteEnterpriseSource as unknown as ReturnType<typeof vi.fn>
const mediaMock = triggerEnterpriseMedia as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { edit: '编辑', delete: '删除', prev: '上一步', next: '下一步', save: '保存', error: '操作失败', success: '成功' },
    },
  },
})

/** a-table stub：按列逐格渲染 bodyCell，让行内断言与按钮触发可测 */
const tableStub = {
  props: ['dataSource'],
  template: `<div class="stub-table">
    <div v-for="row in dataSource || []" :key="row.source_id" class="stub-row">
      <span class="cell-source_id"><slot name="bodyCell" :column="{ key: 'source_id' }" :record="row" /></span>
      <span class="cell-type"><slot name="bodyCell" :column="{ key: 'type' }" :record="row" /></span>
      <span class="cell-created_at"><slot name="bodyCell" :column="{ key: 'created_at' }" :record="row" /></span>
      <span class="cell-status"><slot name="bodyCell" :column="{ key: 'status' }" :record="row" /></span>
      <span class="cell-count"><slot name="bodyCell" :column="{ key: 'ingested_count' }" :record="row" /></span>
      <span class="cell-enabled"><slot name="bodyCell" :column="{ key: 'enabled' }" :record="row" /></span>
      <span class="cell-actions"><slot name="bodyCell" :column="{ key: 'actions' }" :record="row" /></span>
    </div>
    <div v-if="!(dataSource || []).length" class="stub-table-empty" />
  </div>`,
}

const stubs = {
  'a-table': tableStub,
  'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="stub-badge" :data-status="status">{{ text }}</span>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot /><slot name="footer" /></div>' },
  'a-steps': { props: ['current'], template: '<div class="stub-steps" :data-current="current"><slot /></div>' },
  'a-step': { props: ['title'], template: '<div class="stub-step">{{ title }}</div>' },
  'a-form': { template: '<form class="stub-form"><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<label class="stub-form-item"><slot /></label>' },
  'a-input': {
    props: ['value', 'disabled', 'placeholder'],
    emits: ['update:value'],
    template: '<input class="stub-input" :value="value" :data-placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  'a-textarea': {
    props: ['value', 'rows', 'placeholder'],
    emits: ['update:value'],
    template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  'a-select': {
    props: ['value', 'options', 'placeholder'],
    emits: ['update:value'],
    template: `<select class="stub-select" :value="value" @change="$emit('update:value', $event.target.value)">
      <option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>`,
  },
  'a-radio-group': {
    props: ['value'],
    emits: ['update:value'],
    template: `<select class="stub-radio" :value="value" @change="$emit('update:value', $event.target.value)"><slot /></select>`,
  },
  'a-radio': { props: ['value'], template: '<option :value="value"><slot /></option>' },
  'a-switch': {
    props: ['checked', 'disabled', 'size'],
    emits: ['change'],
    template: '<button class="stub-switch" :disabled="disabled" @click="$emit(\'change\', !checked)" />',
  },
  'a-popconfirm': {
    props: ['title'],
    template: '<span class="stub-pop"><button class="pop-confirm-btn" @click="$emit(\'confirm\')"><slot /></button></span>',
  },
  'a-row': { template: '<div class="stub-row-el"><slot /></div>' },
  'a-col': { template: '<div class="stub-col"><slot /></div>' },
  'a-descriptions': { template: '<div class="stub-desc"><slot /></div>' },
  'a-descriptions-item': { props: ['label'], template: '<div class="stub-desc-item"><slot /></div>' },
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

beforeEach(() => {
  listMock.mockReset()
  listMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [], total: 0 } })
  submitMock.mockReset()
  submitMock.mockResolvedValue({ code: 0, message: 'ok', data: sourceRow() })
  ingestMock.mockReset()
  ingestMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { result: { admitted: 2, rejected: 1, batches: 1, truncated: false, cursor: 'fp=x:off=3' } },
  })
  healthMock.mockReset()
  healthMock.mockResolvedValue({ code: 0, message: 'ok', data: { source_id: 'erp_orders', status: 'ok', reason: '' } })
  deleteMock.mockReset()
  deleteMock.mockResolvedValue({ code: 0, message: 'ok', data: { source_id: 'erp_orders' } })
  mediaMock.mockReset()
  mediaMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { status: 'staged', msgid: 'm1', path: 'staged/m1.pdf', size: 9 },
  })
  authUser.role = 'admin'
})

describe('EnterpriseSourcesPage（连接器列表）', () => {
  it('空态加载：只调列表一次，无行渲染', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.stub-row').length).toBe(0)
  })

  it('列表行：类型中文标签、添加时间、已获取计数如实回显', async () => {
    listMock.mockResolvedValue({
      code: 0,
      data: {
        items: [
          sourceRow(),
          sourceRow({ source_id: 'wecom_src', descriptor: { sourceType: 'chat', vendor: 'wecom' } }),
        ],
        total: 2,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const rows = wrapper.findAll('.stub-row')
    expect(rows.length).toBe(2)
    expect(rows[0].find('.cell-type').text()).toContain('数据库')
    expect(rows[1].find('.cell-type').text()).toContain('企微')
    expect(rows[0].find('.cell-created_at').text()).toContain('2026-11-07')
    expect(rows[0].find('.cell-count').text()).toContain('7')
  })

  it('行内检测：走真 health 端点，徽标转"连接正常"；异常显 error 态', async () => {
    listMock.mockResolvedValue({ code: 0, data: { items: [sourceRow()], total: 1 } })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="ent-health-badge"]').text()).toContain('未检测')
    await wrapper.find('[data-testid="ent-health-btn"]').trigger('click')
    await flushPromises()
    expect(healthMock).toHaveBeenCalledWith('erp_orders')
    expect(wrapper.find('[data-testid="ent-health-badge"]').text()).toContain('连接正常')

    healthMock.mockRejectedValue({ response: { data: { detail: '驱动未安装' } } })
    await wrapper.find('[data-testid="ent-health-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="ent-health-badge"]').text()).toContain('连接异常')
    expect(wrapper.find('[data-testid="ent-health-badge"]').text()).toContain('驱动未安装')
  })

  it('删除：确认后走真 DELETE，成功文案点名数据保留', async () => {
    listMock.mockResolvedValue({ code: 0, data: { items: [sourceRow()], total: 1 } })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.pop-confirm-btn').trigger('click')
    await flushPromises()
    expect(deleteMock).toHaveBeenCalledWith('erp_orders')
    const { message } = await import('ant-design-vue')
    expect((message.success as ReturnType<typeof vi.fn>).mock.calls.some((c) => String(c[0]).includes('保留'))).toBe(true)
  })

  it('启用开关：翻转走 POST upsert（enabled 取反）', async () => {
    listMock.mockResolvedValue({ code: 0, data: { items: [sourceRow()], total: 1 } })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.stub-switch').trigger('click')
    await flushPromises()
    expect(submitMock).toHaveBeenCalledWith(
      expect.objectContaining({ source_id: 'erp_orders', enabled: true }),
    )
  })
})

describe('EnterpriseSourcesPage（新增向导）', () => {
  it('步 0 守门：未选连接对象时下一步禁用；选"数据库"后放行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="ent-kind-cards"]').exists()).toBe(true)
    expect((wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.findAll('.kind-card')[0].trigger('click')
    expect((wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('向导创建数据库连接器：必填守门→保存 body 与后端校验对齐（object.column 键）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await wrapper.findAll('.kind-card')[0].trigger('click') // 数据库
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    // 步 1 必填未填 → 下一步禁用
    expect((wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement).disabled).toBe(true)
    const inputs = wrapper.findAll('.stub-input')
    // 顺序：source_id / cursorColumn / host / port / database / table（driver 是 select）
    await inputs[0].setValue('orders_src')
    await inputs[1].setValue('updated_at')
    await inputs[2].setValue('db-host')
    await inputs[3].setValue('5432')
    await inputs[4].setValue('shop')
    await inputs[5].setValue('orders')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    // 步 2 映射
    const step2Inputs = wrapper.findAll('.stub-input')
    await step2Inputs[0].setValue('order_id, status') // columns
    await step2Inputs[1].setValue('order_id') // subject column
    await step2Inputs[2].setValue('has_status') // predicate
    await step2Inputs[3].setValue('status') // object value
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    expect(wrapper.find('[data-testid="ent-wizard-save"]').exists()).toBe(true)
    await wrapper.find('[data-testid="ent-wizard-save"]').trigger('click')
    await flushPromises()

    expect(submitMock).toHaveBeenCalledTimes(1)
    const body = submitMock.mock.calls[0][0]
    expect(body.source_id).toBe('orders_src')
    expect(body.descriptor.sourceType).toBe('sql')
    expect(body.descriptor.driver).toBe('postgresql')
    expect(body.descriptor.host).toBe('db-host')
    expect(body.descriptor.database).toBe('shop')
    expect(body.descriptor.table).toBe('orders')
    expect(body.descriptor.cursorColumn).toBe('updated_at')
    expect(body.descriptor.columns).toEqual(['order_id', 'status'])
    expect(body.descriptor.subject).toEqual({ column: 'order_id' })
    expect(body.descriptor.predicate).toEqual({ termId: 'has_status' })
    expect(body.descriptor.object).toEqual({ kind: 'column', column: 'status' })
  })

  it('向导步 1 类型卡映射：企微卡 → descriptor.sourceType=chat 且 vendor=wecom', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await wrapper.findAll('.kind-card')[2].trigger('click') // 企微
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    const inputs = wrapper.findAll('.stub-input')
    await inputs[0].setValue('wecom_src')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    const step2Inputs = wrapper.findAll('.stub-input')
    await step2Inputs[0].setValue('msg_id, content')
    await step2Inputs[1].setValue('sender')
    await step2Inputs[2].setValue('has_status')
    await step2Inputs[3].setValue('content')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    await wrapper.find('[data-testid="ent-wizard-save"]').trigger('click')
    await flushPromises()
    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor.sourceType).toBe('chat')
    expect(body.descriptor.vendor).toBe('wecom')
    expect(body.descriptor.chatSource).toBeUndefined() // capture 面缺省不落键（存量行为不破）
  })

  it('存档源向导：chatSource=archive 必填守门→保存 body 携带存档配置（批 C7c 对齐）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await wrapper.findAll('.kind-card')[2].trigger('click') // 企微
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    // 步 1 缺省 capture：source_id 填完即可过
    const inputs = wrapper.findAll('.stub-input')
    await inputs[0].setValue('archive_src')
    // 切存档面：未填存档字段 → 守门禁用
    await wrapper.find('.stub-radio').setValue('archive')
    expect((wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement).disabled).toBe(true)
    // 存档字段：sdk / secretEnv 为 stub-input，私钥映射为 stub-textarea
    const archiveInputs = wrapper.findAll('.stub-input')
    await archiveInputs[1].setValue('C:/sdk/libweworkarchive.dll')
    await archiveInputs[2].setValue('NEUROVA_ARCHIVE_SECRET')
    await wrapper.findAll('.stub-textarea')[0].setValue('v1=private_v1.pem')
    expect((wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    // 步 2 映射：object 取结构化列 sender（text 已被编译期守卫拒）
    const step2Inputs = wrapper.findAll('.stub-input')
    await step2Inputs[0].setValue('msg_id, sender')
    await step2Inputs[1].setValue('chat_id')
    await step2Inputs[2].setValue('spoke_in')
    await step2Inputs[3].setValue('sender')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    await wrapper.find('[data-testid="ent-wizard-save"]').trigger('click')
    await flushPromises()

    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor.chatSource).toBe('archive')
    expect(body.descriptor.archiveSdkPath).toBe('C:/sdk/libweworkarchive.dll')
    expect(body.descriptor.archiveSecretEnv).toBe('NEUROVA_ARCHIVE_SECRET')
    expect(body.descriptor.archivePrivateKeys).toEqual({ v1: 'private_v1.pem' })
    expect(body.descriptor.object).toEqual({ kind: 'column', column: 'sender' })
  })
})

describe('EnterpriseSourcesPage（存档源媒体触发）', () => {
  it('媒体按钮仅存档行渲染：触发走真 media 端点，staged 读数回显', async () => {
    listMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        items: [
          sourceRow({
            source_id: 'archive_src',
            descriptor: { sourceType: 'chat', vendor: 'wecom', chatSource: 'archive' },
          }),
          sourceRow({ source_id: 'capture_src', descriptor: { sourceType: 'chat', vendor: 'wecom' } }),
        ],
        total: 2,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const rows = wrapper.findAll('.stub-row')
    expect(rows[0].find('[data-testid="ent-media-btn"]').exists()).toBe(true)
    expect(rows[1].find('[data-testid="ent-media-btn"]').exists()).toBe(false), (
      'capture 面无媒体触发按钮（不摆假能力）')
    await rows[0].find('[data-testid="ent-media-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="ent-media-msgid"]').exists()).toBe(true)
    await wrapper.find('[data-testid="ent-media-msgid"]').setValue('m1')
    await wrapper.find('[data-testid="ent-media-confirm"]').trigger('click')
    await flushPromises()
    expect(mediaMock).toHaveBeenCalledWith('archive_src', 'm1')
    expect((wrapper.find('[data-testid="ent-media-outcome"]').element as HTMLElement).textContent)
      .toContain('staged/m1.pdf')
  })

  it('媒体引用过期：502 原话进错误读数（有引用不冒充可检索）', async () => {
    listMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        items: [sourceRow({
          source_id: 'archive_src',
          descriptor: { sourceType: 'chat', vendor: 'wecom', chatSource: 'archive' },
        })],
        total: 1,
      },
    })
    mediaMock.mockRejectedValue({ response: { status: 502, data: { detail: 'GetMediaData 失败 ret=3——引用过期' } } })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-media-btn"]').trigger('click')
    await wrapper.find('[data-testid="ent-media-msgid"]').setValue('m1')
    await wrapper.find('[data-testid="ent-media-confirm"]').trigger('click')
    await flushPromises()
    expect((wrapper.find('[data-testid="ent-media-outcome"]').element as HTMLElement).textContent)
      .toContain('引用过期')
  })
})

describe('EnterpriseSourcesPage（编辑）', () => {
  it('编辑预填：kind 由描述符反推、source_id 锁定、保存保持 vendor', async () => {
    listMock.mockResolvedValue({
      code: 0,
      data: {
        items: [sourceRow({
          source_id: 'wecom_src',
          descriptor: { sourceType: 'chat', vendor: 'wecom', columns: ['msg_id'],
                        subject: { column: 'sender' },
                        predicate: { termId: 'has_status' },
                        object: { kind: 'column', column: 'content' } },
        })],
        total: 1,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-edit-btn"]').trigger('click')
    // 编辑直进步 1（选型锁定），source_id 已预填且 disabled
    const sid = wrapper.find('[data-testid="ent-wizard-source-id"]')
    expect((sid.element as HTMLInputElement).value).toBe('wecom_src')
    expect((sid.element as HTMLInputElement).disabled).toBe(true)
    // 直接到步 3 保存（步骤 1/2 已有预填值，直接点两次下一步）
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    await wrapper.find('[data-testid="ent-wizard-save"]').trigger('click')
    await flushPromises()
    const body = submitMock.mock.calls[0][0]
    expect(body.source_id).toBe('wecom_src')
    expect(body.descriptor.sourceType).toBe('chat')
    expect(body.descriptor.vendor).toBe('wecom')
  })
})

describe('EnterpriseSourcesPage（摄取）', () => {
  it('逐行摄取：四数如实报', async () => {
    listMock.mockResolvedValue({ code: 0, data: { items: [sourceRow()], total: 1 } })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-ingest-btn"]').trigger('click')
    await flushPromises()
    expect(ingestMock).toHaveBeenCalledWith('erp_orders')
    const { message } = await import('ant-design-vue')
    expect((message.success as ReturnType<typeof vi.fn>).mock.calls.some((c) => String(c[0]).includes('2'))).toBe(true)
  })

  it('skipped 走 info 不谎报成功', async () => {
    listMock.mockResolvedValue({ code: 0, data: { items: [sourceRow()], total: 1 } })
    ingestMock.mockResolvedValue({ code: 0, data: { result: { skipped: true, reason: 'source 未启用（默认关）' } } })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-ingest-btn"]').trigger('click')
    await flushPromises()
    const { message } = await import('ant-design-vue')
    expect((message.info as ReturnType<typeof vi.fn>).mock.calls.some((c) => String(c[0]).includes('未启用'))).toBe(true)
  })
})

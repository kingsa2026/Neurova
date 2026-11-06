/**
 * OntologyStudioPage — UI-0 Studio 壳契约测试。
 *
 * 契约面：
 * - 概览分区读 /ontology/schema 信封并渲染术语/规则计数与 upper-lite 树；
 * - 形状分区读 shapes REST 列表（空态不造假行）；
 * - CQ 分区为静态追溯表（implemented/planned 闭集）；
 * - 权限态：非管理员看不到术语编辑入口；
 * - 关系候选审批（管理员）：approve 动作调用候选 API 并刷新 pending 计数。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__ontologyStudioAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__ontologyStudioAuthUser
    },
  }),
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: { value: 'a1' },
    currentAgent: { value: { name: 'AgentX' } },
    agentLoading: { value: false },
  }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/api/modules/ontology', () => ({
  getOntologySchema: vi.fn(),
  listRelationCandidates: vi.fn(),
  listOntologyTerms: vi.fn(),
  createOntologyTerm: vi.fn(),
  updateOntologyTerm: vi.fn(),
  deleteOntologyTerm: vi.fn(),
  approveRelationCandidate: vi.fn(),
  rejectRelationCandidate: vi.fn(),
  getDerivationChain: vi.fn(),
  resolveOntologyIri: vi.fn(),
  runOntologyPipeline: vi.fn(),
  getOntologyPipelineDiff: vi.fn(),
  listOntologyShapes: vi.fn(),
  createOntologyShape: vi.fn(),
  deleteOntologyShape: vi.fn(),
  rollbackOntologyPipeline: vi.fn(),
  accessQuery: vi.fn(),
  accessAnalyze: vi.fn(),
  accessValidate: vi.fn(),
  accessUse: vi.fn(),
  exportOntologyTtl: vi.fn(),
}))

import { message } from 'ant-design-vue'
import {
  approveRelationCandidate,
  createOntologyTerm,
  getOntologySchema,
  listOntologyShapes,
  listOntologyTerms,
  listRelationCandidates,
  rollbackOntologyPipeline,
} from '@/api/modules/ontology'
import OntologyStudioPage from '@/pages/ontology-studio/OntologyStudioPage.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const schemaMock = getOntologySchema as unknown as ReturnType<typeof vi.fn>
const candidatesMock = listRelationCandidates as unknown as ReturnType<typeof vi.fn>
const approveMock = approveRelationCandidate as unknown as ReturnType<typeof vi.fn>
const shapesMock = listOntologyShapes as unknown as ReturnType<typeof vi.fn>
const rollbackMock = rollbackOntologyPipeline as unknown as ReturnType<typeof vi.fn>
const termsMock = listOntologyTerms as unknown as ReturnType<typeof vi.fn>
const createTermMock = createOntologyTerm as unknown as ReturnType<typeof vi.fn>

const schemaPayload = {
  code: 0,
  message: 'success',
  data: {
    terms: [
      { term_id: 'Entity', kind: 'concept', label: '实体', parent_term_id: null, version: 'v1', deprecated: false, aliases: [] },
      { term_id: 'Document', kind: 'concept', label: '文档', parent_term_id: 'Entity', version: 'v1', deprecated: false, aliases: [] },
      { term_id: 'related_to', kind: 'relation', label: '关联', parent_term_id: null, version: 'v1', deprecated: false, aliases: [], symmetric: true, transitive: false, cardinality: null, inverse_of: '' },
    ],
    rules: [{ rule_id: 'is_a_transitive', head_predicate: 'is_a', shape: 'relay', enabled: true, version: 'v1' }],
    schema_version: 33,
    tenant_scoped: true,
  },
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: {
        refresh: '刷新',
        actions: '操作',
        confirm: '确认',
        cancel: '取消',
        yes: '是',
        no: '否',
        noData: '暂无数据',
        required: '此字段为必填',
      },
    },
  },
})

const mountPage = () =>
  mount(OntologyStudioPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-alert': { props: ['message', 'description'], template: '<div class="stub-alert">{{ message }}<slot /></div>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-search': {
          props: ['value'],
          emits: ['update:value', 'search'],
          template: '<input class="stub-search" :value="value" @input="$emit(\'update:value\', $event.target.value)" @keydown.enter="$emit(\'search\')" />',
        },
        'a-input-number': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-num" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
        },
        'a-select': { props: ['value'], emits: ['update:value'], template: '<select class="stub-select" :value="value" @change="$emit(\'update:value\', $event.target.value)"><slot /></select>' },
        'a-select-option': { props: ['value'], template: '<option :value="value"><slot /></option>' },
        'a-checkbox': { props: ['checked'], emits: ['update:checked'], template: '<input type="checkbox" :checked="checked" />' },
        'a-textarea': { props: ['value'], emits: ['update:value'], template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-radio-group': { props: ['value'], emits: ['update:value'], template: '<div class="stub-radio-group"><slot /></div>' },
        'a-radio-button': { props: ['value'], template: '<button class="stub-radio" @click="$parent?.$emit(\'update:value\', $props.value)"><slot /></button>' },
        'a-popconfirm': { template: '<div><slot /></div>' },
        'a-button': { template: '<button class="stub-a-btn"><slot /></button>' },
        'a-tooltip': { template: '<div><slot /></div>' },
        'a-tabs': { props: ['activeKey'], emits: ['update:activeKey'], template: '<div class="stub-tabs"><slot /></div>' },
        'a-tab-pane': { props: ['tab'], template: '<div class="stub-tab-pane"><slot /></div>' },
        'a-drawer': { props: ['open'], emits: ['update:open'], template: '<div v-if="open" class="stub-drawer"><slot /></div>' },
      },
    },
  })

beforeEach(() => {
  schemaMock.mockReset()
  candidatesMock.mockReset()
  approveMock.mockReset()
  shapesMock.mockReset()
  rollbackMock.mockReset()
  termsMock.mockReset()
  createTermMock.mockReset()
  ;(message.success as ReturnType<typeof vi.fn>).mockClear()
  ;(message.error as ReturnType<typeof vi.fn>).mockClear()
  authUser.role = 'admin'
  schemaMock.mockResolvedValue(schemaPayload)
  candidatesMock.mockResolvedValue({
    code: 0,
    message: 'success',
    data: {
      items: [
        {
          candidate_id: 'cand-1',
          tenant_id: 'default',
          surface: '隶属于',
          normalized_surface: 'belongs_to',
          source_entry_id: 'doc-1',
          source_text: '订单隶属于客户',
          confidence: 0.87,
          status: 'pending',
          created_at: '',
          reviewed_at: '',
          reviewed_by: '',
          promoted_term_id: '',
        },
      ],
    },
  })
  approveMock.mockResolvedValue({
    code: 0,
    message: 'success',
    data: { candidate: { candidate_id: 'cand-1', status: 'approved', promoted_term_id: 'belongs_to' }, activity_id: 'act-1' },
  })
  shapesMock.mockResolvedValue({ code: 0, message: 'success', data: { items: [], total: 0 } })
  rollbackMock.mockResolvedValue({
    code: 0, message: 'success',
    data: { restored: { terms: 1, rules: 0, shapes: 0 }, audit: {}, activity_id: 'act-r' },
  })
  termsMock.mockResolvedValue({
    code: 0,
    message: 'success',
    data: {
      items: [
        { term_id: 'Order', kind: 'concept', label: '订单', parent_term_id: null, version: 'v1',
          deprecated: false, aliases: [], domain_terms: [], range_terms: [], range_kinds: [],
          disjoint_with: [], required_props: [], identity_keys: [], labels: {}, alt_labels: {},
          qualifier_schema: {}, external_iris: {}, module: 'domain' },
      ],
      total: 1,
      next_cursor: '',
    },
  })
  createTermMock.mockResolvedValue({ code: 0, message: 'success', data: { term: {}, activity_id: 'act-t' } })
})

describe('OntologyStudioPage（UI-0）', () => {
  it('概览：读 schema 信封渲染术语/规则计数、租户标记与 upper-lite 树', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="studio-tenant-scoped"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="overview-term-count"]').text()).toBe('3')
    expect(wrapper.find('[data-testid="overview-rule-count"]').text()).toBe('1')
    expect(wrapper.find('[data-testid="overview-relation-count"]').text()).toBe('1')
    expect(wrapper.find('[data-testid="studio-upper-tree"]').text()).toContain('Entity')
    expect(wrapper.find('[data-testid="studio-upper-tree"]').text()).toContain('Continuant')
    expect(wrapper.find('[data-testid="studio-upper-tree"]').text()).toContain('Occurrent')
  })

  it('形状分区：REST 列表与新建入口可用，空态不渲染假行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-shapes"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="studio-shapes"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="shapes-new"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="shapes-empty"]').exists()).toBe(true)
    expect(shapesMock).toHaveBeenCalled()
  })

  it('术语声明写面：labels/module/identity_keys/qualifier_schema 随 POST 交出去', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-terms"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="terms-new"]').trigger('click')
    await wrapper.find('[data-testid="term-term-id"]').setValue('RiskOrder')
    await wrapper.find('[data-testid="term-module"]').setValue('domain')
    await wrapper.find('[data-testid="term-labels"]').setValue('{"zh": "风险订单", "en": "Risk Order"}')
    await wrapper.find('[data-testid="term-alt-labels"]').setValue('{"zh": ["高危单"]}')
    await wrapper.find('[data-testid="term-identity-keys"]').setValue('external_id')
    await wrapper.find('[data-testid="term-qualifier-schema"]').setValue('{"carrier": {"required": true}}')
    await wrapper.find('[data-testid="term-save"]').trigger('click')
    await flushPromises()

    expect(createTermMock).toHaveBeenCalledTimes(1)
    expect(createTermMock.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        term_id: 'RiskOrder',
        kind: 'concept',
        module: 'domain',
        labels: { zh: '风险订单', en: 'Risk Order' },
        alt_labels: { zh: ['高危单'] },
        identity_keys: ['external_id'],
        qualifier_schema: { carrier: { required: true } },
      }),
    )
  })

  it('发布分区：rollback 调用 REST 并把结果落回执', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-release"]').trigger('click')
    await wrapper.find('[data-testid="rollback-baseline"]').setValue('kb_1')
    await wrapper.find('[data-testid="rollback-btn"]').trigger('click')
    await flushPromises()
    expect(rollbackMock).toHaveBeenCalledWith({ toBaselineId: 'kb_1', reason: '' })
    expect(wrapper.find('[data-testid="rollback-result"]').exists()).toBe(true)
    expect(message.success).toHaveBeenCalled()
  })

  it('CQ 分区：静态追溯表 11 行，implemented/planned 闭集', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-cq"]').trigger('click')
    const rows = wrapper.findAll('[data-testid="cq-status"]')
    expect(rows.length).toBe(11)
  })

  it('权限态：非管理员不显示「新建术语」按钮', async () => {
    authUser.role = 'user'
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-terms"]').trigger('click')
    expect(wrapper.find('[data-testid="terms-new"]').exists()).toBe(false)
  })

  it('关系候选（管理员）：approve 动作调用候选 API 并触发 pending 刷新', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="studio-nav-relations"]').trigger('click')
    await flushPromises()
    const approveBtn = wrapper.find('[data-testid="candidate-approve"]')
    expect(approveBtn.exists()).toBe(true)
    // 批准动作旁显示来源文本与置信度（§15.4：候选只人工批准）
    expect(wrapper.find('[data-testid="studio-relations"]').text()).toContain('订单隶属于客户')
    expect(wrapper.find('[data-testid="studio-relations"]').text()).toContain('0.87')
    await approveBtn.trigger('click')
    await flushPromises()
    expect(approveMock).toHaveBeenCalledWith('cand-1')
    expect(message.success).toHaveBeenCalled()
  })
})

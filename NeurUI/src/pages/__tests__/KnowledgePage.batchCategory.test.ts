/**
 * KnowledgePage — 列表批量分类 TDD 判据（先红后绿）
 *
 * 背景：列表页只有单条编辑改分类（编辑弹窗 → PUT /knowledge/{id}），
 * 多选归类无处发生。本批判据钉住批量分类的完整交互契约：
 *
 * 1. 表格提供行多选（rowSelection）；不可管理行（非属主且非 admin）
 *    勾选禁用——与后端 PUT 的属主/管理员权限面一致，不造平行口径。
 * 2. 有选中即出现批量操作条：已选计数 + 批量分类入口 + 取消选择。
 * 3. 批量分类弹窗的分类下拉复用分类注册表单源（categoryOptions）。
 * 4. 应用时逐条走既有 updateKnowledgeNode（PUT），payload 只带 category
 *    （不带正文，避免触发 facts 重抽门控）；聚合成功/失败：
 *    全成 → 成功提示 + 刷新 + 清空选择；部分 → warning + 刷新；
 *    全败 → error（detail 原话优先）+ 保留选择供重试。
 * 5. 未选目标分类不得发请求。
 * 6. 结果集口径变化（切 scope）清空选择，防对不可见条目静默动手。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import KnowledgePage from '@/pages/KnowledgePage.vue'
import { message } from 'ant-design-vue'

vi.mock('@/api/modules/knowledge', () => ({
  getKnowledgeNodes: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  searchKnowledge: vi.fn(),
  createKnowledgeNode: vi.fn(),
  updateKnowledgeNode: vi.fn().mockResolvedValue({ data: {} }),
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
  listKnowledgeConflicts: vi.fn().mockResolvedValue({ data: [] }),
  resolveKnowledgeConflict: vi.fn(),
  listDeletedKnowledge: vi.fn().mockResolvedValue({ data: [] }),
  restoreKnowledgeNode: vi.fn(),
  listKnowledgeRevisions: vi.fn().mockResolvedValue({ data: [] }),
  syncKbConfig: vi.fn(),
  previewChunking: vi.fn(),
  listIngressTasks: vi.fn().mockResolvedValue({ data: { tasks: [], stats: {} } }),
  getIngressTask: vi.fn(),
  cancelIngressTask: vi.fn(),
  listKnowledgeChunks: vi.fn().mockResolvedValue({ data: [] }),
  updateKnowledgeChunk: vi.fn(),
  listKnowledgeChunkRevisions: vi.fn().mockResolvedValue({ data: [] }),
  listResolutionReviews: vi.fn().mockResolvedValue({ data: [] }),
  resolveResolutionReview: vi.fn(),
  runEntityResolution: vi.fn(),
  listKnowledgeCategories: vi.fn().mockResolvedValue({
    data: [
      { category_id: 'tech', name: '技术', is_active: true },
      { category_id: 'product', name: '产品', is_active: true },
    ],
  }),
}))

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u-1', username: 'alice', role: 'user' } }),
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' } }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import { getKnowledgeNodes, updateKnowledgeNode } from '@/api/modules/knowledge'

const OWNED_A = {
  id: 'kid-a', knowledge_id: 'kid-a', title: '条目A', category: 'general',
  content: '甲', visibility: 'private', owner_user_id: 'u-1',
}
const OWNED_B = {
  id: 'kid-b', knowledge_id: 'kid-b', title: '条目B', category: 'general',
  content: '乙', visibility: 'private', owner_user_id: 'u-1',
}
const FOREIGN = {
  id: 'kid-c', knowledge_id: 'kid-c', title: '他人条目', category: 'general',
  content: '丙', visibility: 'public', owner_user_id: 'u-2',
}
const ITEMS = [OWNED_A, OWNED_B, FOREIGN]

const messages = {
  knowledge: {
    title: '知识库',
    batchSelected: '已选 {n} 项',
    batchCategorize: '批量分类',
    batchClearSelection: '取消选择',
    batchCategorizeTitle: '批量分类',
    batchCategorizeSuccess: '已更新 {n} 条知识的分类',
    batchCategorizePartial: '分类更新：成功 {success} 条，失败 {fail} 条',
    batchCategorizeFailed: '分类更新失败',
    batchCategorizeNoCategory: '请选择目标分类',
  },
}

const stubs = {
  GlassPanel: { template: '<div><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  AnnotationDrawer: { template: '<div />' },
  KnowledgeLineageDrawer: { template: '<div />' },
  CategoryManagerModal: { template: '<div />' },
  // 行多选契约面：rowSelection 存在才渲染勾选框；disabled 由 getCheckboxProps 决定
  'a-table': {
    props: ['dataSource', 'columns', 'rowSelection', 'pagination', 'loading'],
    methods: {
      toggleRow(record: any, checked: boolean) {
        const sel = (this as any).rowSelection
        const keys = (sel.selectedRowKeys || []).filter((k: string) => k !== record.id)
        if (checked) keys.push(record.id)
        sel.onChange(keys, [])
      },
    },
    template: `<div class="ant-table"><div v-for="r in dataSource || []" :key="r.id" class="ant-table-row" :data-id="r.id"><input v-if="rowSelection" type="checkbox" class="row-select" :data-id="r.id" :disabled="rowSelection.getCheckboxProps ? !!rowSelection.getCheckboxProps(r).disabled : false" :checked="(rowSelection.selectedRowKeys || []).includes(r.id)" @change="toggleRow(r, $event.target.checked)" /><template v-for="c in columns || []" :key="c.key"><slot name="bodyCell" :column="c" :record="r" /></template></div></div>`,
  },
  'a-modal': {
    props: ['open', 'title', 'confirmLoading'],
    emits: ['ok', 'cancel', 'update:open'],
    template: '<div v-if="open" class="ant-modal" :data-title="title"><h3>{{ title }}</h3><slot/><div class="modal-actions"><button class="modal-ok" @click="$emit(\'ok\')">OK</button><button class="modal-cancel" @click="$emit(\'cancel\')">Cancel</button></div></div>',
  },
  'a-select': { props: ['value', 'options', 'placeholder'], emits: ['update:value'], template: '<select class="ant-select" :value="value" @change="$emit(\'update:value\', $event.target.value)"><option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-input': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-input-search': { props: ['value', 'placeholder'], emits: ['update:value', 'search'], template: '<input class="ant-input-search" :value="value" @input="$emit(\'update:value\', $event.target.value)" @keyup.enter="$emit(\'search\', value)" />' },
  'a-checkbox': { template: '<div />' },
  'a-radio-button': { template: '<div />' },
  'a-radio-group': { template: '<div />' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="form-item"><slot/></div>' },
  'a-upload-dragger': { template: '<div><slot/></div>' },
  'a-divider': { template: '<hr />' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(KnowledgePage, { global: { plugins: [i18n], stubs } })
}

async function mountWithItems() {
  vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: ITEMS, total: ITEMS.length } } as any)
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

async function selectOwnedRows(wrapper: ReturnType<typeof mountPage>) {
  expect(wrapper.find('input.row-select').exists(), '表格须提供行多选勾选框').toBe(true)
  await wrapper.find('input.row-select[data-id="kid-a"]').setValue(true)
  await wrapper.find('input.row-select[data-id="kid-b"]').setValue(true)
  await flushPromises()
}

function batchModal(wrapper: ReturnType<typeof mountPage>) {
  return wrapper.findAll('.ant-modal').find((m) => m.attributes('data-title') === '批量分类')
}

async function openBatchModal(wrapper: ReturnType<typeof mountPage>) {
  const bar = wrapper.find('.kb-batch-bar')
  expect(bar.exists(), '选中后须出现批量操作条').toBe(true)
  const btn = bar.findAll('button').find((b) => b.text() === '批量分类')
  expect(btn, '批量操作条须有批量分类入口').toBeTruthy()
  await btn!.trigger('click')
  await flushPromises()
  const modal = batchModal(wrapper)
  expect(modal, '须打开批量分类弹窗').toBeTruthy()
  return modal!
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)
  vi.mocked(updateKnowledgeNode).mockResolvedValue({ data: {} } as any)
})

describe('KnowledgePage 批量分类', () => {
  it('行多选：属主行可勾选，非属主行勾选禁用（与 PUT 权限面同口径）', async () => {
    const wrapper = await mountWithItems()
    const boxes = wrapper.findAll('input.row-select')
    expect(boxes.length, '每行须有勾选框').toBe(3)
    expect(wrapper.find('input.row-select[data-id="kid-a"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('input.row-select[data-id="kid-b"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('input.row-select[data-id="kid-c"]').attributes('disabled'), '他人条目不得勾选').toBeDefined()
    wrapper.unmount()
  })

  it('选中后出现批量条：已选计数 + 取消选择可清空', async () => {
    const wrapper = await mountWithItems()
    expect(wrapper.find('.kb-batch-bar').exists(), '未选中时不得出现批量条').toBe(false)
    await selectOwnedRows(wrapper)
    const bar = wrapper.find('.kb-batch-bar')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).toContain('已选 2 项')
    const clearBtn = bar.findAll('button').find((b) => b.text() === '取消选择')
    expect(clearBtn).toBeTruthy()
    await clearBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.kb-batch-bar').exists(), '取消选择后批量条消失').toBe(false)
    wrapper.unmount()
  })

  it('批量应用：逐条 PUT 只带 category，全成 → 成功提示 + 刷新 + 清空选择', async () => {
    const wrapper = await mountWithItems()
    await selectOwnedRows(wrapper)
    vi.mocked(getKnowledgeNodes).mockClear()
    const modal = await openBatchModal(wrapper)

    await modal.find('select.ant-select').setValue('tech')
    await modal.find('button.modal-ok').trigger('click')
    await flushPromises()

    expect(updateKnowledgeNode).toHaveBeenCalledTimes(2)
    expect(updateKnowledgeNode).toHaveBeenCalledWith('kid-a', { category: 'tech' }, { agent_id: 'default' })
    expect(updateKnowledgeNode).toHaveBeenCalledWith('kid-b', { category: 'tech' }, { agent_id: 'default' })
    expect(message.success).toHaveBeenCalledTimes(1)
    expect(vi.mocked(message.success).mock.calls[0][0]).toContain('2 条')
    expect(getKnowledgeNodes, '有成功须刷新列表').toHaveBeenCalledTimes(1)
    expect((wrapper.vm as any).selectedRowKeys, '成功后清空选择').toHaveLength(0)
    expect(batchModal(wrapper), '成功后弹窗关闭').toBeUndefined()
    wrapper.unmount()
  })

  it('部分失败：warning 聚合读数，仍刷新列表', async () => {
    const wrapper = await mountWithItems()
    await selectOwnedRows(wrapper)
    vi.mocked(getKnowledgeNodes).mockClear()
    vi.mocked(updateKnowledgeNode)
      .mockResolvedValueOnce({ data: {} } as any)
      .mockRejectedValueOnce({ response: { status: 403, data: { detail: '无权限' } } } as any)
    const modal = await openBatchModal(wrapper)

    await modal.find('select.ant-select').setValue('tech')
    await modal.find('button.modal-ok').trigger('click')
    await flushPromises()

    expect(message.warning).toHaveBeenCalledTimes(1)
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('成功 1 条，失败 1 条')
    expect(getKnowledgeNodes, '部分成功也要刷新').toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('全部失败：error 显 detail 原话，不刷新，保留选择供重试', async () => {
    const wrapper = await mountWithItems()
    await selectOwnedRows(wrapper)
    vi.mocked(getKnowledgeNodes).mockClear()
    vi.mocked(updateKnowledgeNode).mockRejectedValue({ response: { status: 403, data: { detail: '批量原话' } } } as any)
    const modal = await openBatchModal(wrapper)

    await modal.find('select.ant-select').setValue('tech')
    await modal.find('button.modal-ok').trigger('click')
    await flushPromises()

    expect(message.success, '失败不得提示成功').not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('批量原话')
    expect(getKnowledgeNodes, '无成功不得刷新').not.toHaveBeenCalled()
    expect((wrapper.vm as any).selectedRowKeys, '全败保留选择供重试').toHaveLength(2)
    wrapper.unmount()
  })

  it('未选目标分类：不发请求，提示选择分类', async () => {
    const wrapper = await mountWithItems()
    await selectOwnedRows(wrapper)
    const modal = await openBatchModal(wrapper)

    await modal.find('button.modal-ok').trigger('click')
    await flushPromises()

    expect(updateKnowledgeNode, '未选分类不得发请求').not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('请选择目标分类')
    wrapper.unmount()
  })

  it('切 scope（结果集口径变化）清空选择', async () => {
    const wrapper = await mountWithItems()
    await selectOwnedRows(wrapper)
    expect((wrapper.vm as any).selectedRowKeys).toHaveLength(2)
    ;(wrapper.vm as any).onScopeChange()
    await flushPromises()
    expect((wrapper.vm as any).selectedRowKeys, '切 scope 后不得残留选择').toHaveLength(0)
    wrapper.unmount()
  })
})
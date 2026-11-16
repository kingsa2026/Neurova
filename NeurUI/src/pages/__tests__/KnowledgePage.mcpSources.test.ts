import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import KnowledgePage from '@/pages/KnowledgePage.vue'
import { message } from 'ant-design-vue'

/**
 * P1-25（审计 2026-11-16）：KnowledgePage「MCP 信息源」按钮点击无任何效果——
 * 按钮 `@click="mcpVisible = true; fetchMcpSources()"` 有，script :1140-1260 一整套
 * 逻辑与 .kb-mcp-* 样式都在，但 mcpVisible/mcpSources/mcpForm 在模板零挂载点：
 * 没有任何弹层渲染，整块 MCP 管理面成死码。
 *
 * 按拍板「能接线先接线」：补回弹层模板。本测试驱动完整链：
 * 按钮 → 弹层渲染 → 拉源列表 → 登记表单 → 保存 → createMcpSource。
 */
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
  requestConflictLlmAdvice: vi.fn(),
  listDeletedKnowledge: vi.fn().mockResolvedValue({ data: [] }),
  restoreKnowledgeNode: vi.fn(),
  listKnowledgeVersions: vi.fn().mockResolvedValue({ data: [] }),
  listKnowledgeRevisions: vi.fn().mockResolvedValue({ data: [] }),
  rollbackKnowledgeRevision: vi.fn(),
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
  listKnowledgeCategories: vi.fn().mockResolvedValue({ data: [] }),
  importKnowledgeFile: vi.fn(),
  importKnowledgeFromUrl: vi.fn(),
  listMcpSources: vi.fn(),
  probeMcpTools: vi.fn(),
  createMcpSource: vi.fn(),
  updateMcpSource: vi.fn(),
  pullMcpSource: vi.fn(),
  deleteMcpSource: vi.fn(),
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

import { getKnowledgeNodes, listMcpSources, probeMcpTools, createMcpSource } from '@/api/modules/knowledge'

const messages = {
  common: {
    edit: '编辑', cancel: '取消', save: '保存', required: '必填', error: '出错了',
    refresh: '刷新', delete: '删除', search: '搜索',
  },
  knowledge: {
    title: '知识库',
    mcpTitle: 'MCP 信息源',
    mcpNew: '登记信息源',
    mcpName: '名称',
    mcpEndpoint: 'MCP Endpoint（streamable-http URL）',
    mcpToken: '鉴权 Token（可选）',
    mcpPickTool: '选择工具',
    mcpProbe: '探测工具',
    mcpToolsFound: '发现 {count} 个工具',
    mcpArgsJson: '工具参数 JSON',
    mcpEmpty: '还没有登记 MCP 信息源',
    mcpPull: '拉取',
    mcpDeleteConfirm: '删除该信息源？',
    mcpCreated: '信息源已登记',
    editItem: '编辑知识项',
  },
}

const stubs = {
  GlassPanel: { template: '<div><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  AnnotationDrawer: { template: '<div />' },
  KnowledgeLineageDrawer: { template: '<div />' },
  CategoryManagerModal: { template: '<div />' },
  'a-table': { props: ['dataSource', 'columns'], template: '<div class="ant-table"><div v-for="r in dataSource || []" :key="r.id" class="ant-table-row"><template v-for="c in columns || []" :key="c.key"><slot name="bodyCell" :column="c" :record="r" /></template></div></div>' },
  'a-modal': {
    props: ['open', 'title', 'confirmLoading'],
    emits: ['ok', 'cancel', 'update:open'],
    template: '<div v-if="open" class="ant-modal" :data-title="title"><h3>{{ title }}</h3><slot/></div>',
  },
  'a-select': { props: ['value', 'options', 'placeholder'], emits: ['update:value'], template: '<select class="ant-select" :value="value"><option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-input': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-input-password': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input-password" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], emits: ['update:value'], template: '<textarea class="ant-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="form-item"><label>{{ label }}</label><slot/></div>' },
  'a-popconfirm': { template: '<span><slot/></span>' },
  'a-divider': { template: '<hr />' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span><slot/></span>' },
  'a-space': { template: '<div><slot/></div>' },
  'a-empty': { template: '<div />' },
  'a-upload-dragger': { template: '<div><slot/></div>' },
  'a-checkbox': { template: '<div />' },
  'a-radio-button': { template: '<div />' },
  'a-radio-group': { template: '<div />' },
  'a-input-search': { props: ['value', 'placeholder'], emits: ['update:value', 'search'], template: '<input class="ant-input-search" :value="value" @input="$emit(\'update:value\', $event.target.value)" @keyup.enter="$emit(\'search\', value)" />' },
  'a-input-number': { template: '<input />' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, messages: { 'zh-CN': messages } })
  return mount(KnowledgePage, { global: { plugins: [i18n], stubs } })
}

async function openMcpModal() {
  const wrapper = mountPage()
  await flushPromises()
  const btn = wrapper.findAll('button').find((b) => (b.text() || '').includes('MCP 信息源'))
  expect(btn, '「MCP 信息源」入口按钮应渲染').toBeTruthy()
  await btn!.trigger('click')
  await flushPromises()
  return wrapper
}

describe('KnowledgePage — MCP 信息源弹层接线（P1-25）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as never)
  })

  it('点击「MCP 信息源」渲染弹层并拉取信息源列表（修复前：点击零效果）', async () => {
    vi.mocked(listMcpSources).mockResolvedValue({
      data: { items: [{ source_id: 'src-1', name: 'docs-server', endpoint: 'http://mcp.local/http' }] },
    } as never)

    const wrapper = await openMcpModal()

    expect(listMcpSources).toHaveBeenCalled()
    const modal = wrapper.findAll('.ant-modal').find((m) => m.attributes('data-title') === 'MCP 信息源')
    expect(modal, 'MCP 弹层应渲染（mcpVisible 此前在模板零挂载点）').toBeTruthy()
    expect(modal!.text()).toContain('docs-server')
    expect(modal!.text()).toContain('http://mcp.local/http')
    expect(modal!.text()).toContain('拉取')
  })

  it('登记表单 → 探测工具 → 保存，链路直达既有 script 逻辑', async () => {
    vi.mocked(listMcpSources).mockResolvedValue({ data: { items: [] } } as never)
    vi.mocked(probeMcpTools).mockResolvedValue({ data: { tools: [{ name: 'search', description: '' }] } } as never)
    vi.mocked(createMcpSource).mockResolvedValue({ data: {} } as never)

    const wrapper = await openMcpModal()
    const modal = wrapper.findAll('.ant-modal').find((m) => m.attributes('data-title') === 'MCP 信息源')!

    // 打开登记表单
    const newBtn = modal.findAll('button').find((b) => (b.text() || '').includes('登记信息源'))
    expect(newBtn).toBeTruthy()
    await newBtn!.trigger('click')
    await flushPromises()

    // 填名称/Endpoint
    const inputs = modal.findAll('input.ant-input')
    await inputs[0].setValue('docs-server')
    await inputs[1].setValue('http://mcp.local/http')

    // 探测工具（走 probeMcpTools）
    const probeBtn = modal.findAll('button').find((b) => (b.text() || '').includes('探测工具'))
    expect(probeBtn).toBeTruthy()
    await probeBtn!.trigger('click')
    await flushPromises()
    expect(probeMcpTools).toHaveBeenCalledWith({ endpoint: 'http://mcp.local/http', auth_token: '' })

    // 保存（走 createMcpSource，payload 带 agent_id 单源）
    const saveBtn = modal.findAll('button').find((b) => (b.text() || '').includes('保存'))
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(createMcpSource).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(createMcpSource).mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload).toMatchObject({ name: 'docs-server', endpoint: 'http://mcp.local/http', agent_id: 'default' })
    expect(message.success).toHaveBeenCalled()
  })

  it('空列表显示空态文案（kb-src-empty），不再是无任何反馈的死按钮', async () => {
    vi.mocked(listMcpSources).mockResolvedValue({ data: { items: [] } } as never)

    const wrapper = await openMcpModal()
    const modal = wrapper.findAll('.ant-modal').find((m) => m.attributes('data-title') === 'MCP 信息源')!
    expect(modal.text()).toContain('还没有登记 MCP 信息源')
  })
})

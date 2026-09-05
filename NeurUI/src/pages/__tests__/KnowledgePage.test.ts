/**
 * KnowledgePage — 远程知识库配置弹窗（分类型表单）TDD 测试
 *
 * 背景（2026-09-01）：
 * 弹窗原先所有远程库类型共用「名称 + 类型 + API Key」三字段，与后端
 * 适配器契约不对齐——feishu 需要 app_id/app_secret、ima 需要
 * base_url/token、custom 需要 api_url，均无处填写。
 *
 * 契约（防回归）：
 * 1. 表单字段按 source_type 动态渲染，与后端适配器参数一一对应：
 *    - iflow:  name + API Key（必填）+ base_url（可选）+ dataset_id（可选）
 *    - feishu: name + App ID（必填）+ App Secret（必填，走加密通道）+ base_url（可选）+ space_id（可选）
 *    - ima:    name + base_url（必填）+ Token（必填，走加密通道）+ knowledge_base_id（可选）+ allow_local（开关）
 *    - custom: name + API URL（必填）+ API Key（可选）+ dataset_id（可选）
 * 2. 提交 payload 分组正确：主凭据走顶层 api_key（后端加密存储），
 *    其余参数进 settings（后端原样透传适配器）。
 * 3. 必填缺失时不提交。
 * 4. 类型切换时残留凭据重置，不把上一类型的值带进下一类型的 payload。
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
  updateKnowledgeNode: vi.fn(),
  deleteKnowledgeNode: vi.fn(),
  hybridKnowledgeSearch: vi.fn(),
  shareKnowledgeNode: vi.fn(),
  submitKnowledgeToPublic: vi.fn(),
  listPublicSubmissions: vi.fn().mockResolvedValue({ data: [] }),
  reviewKnowledgePublic: vi.fn(),
  listKbConfigs: vi.fn().mockResolvedValue({ data: { configs: [] } }),
  createKbConfig: vi.fn().mockResolvedValue({ data: { id: 'kbc_new' } }),
  deleteKbConfig: vi.fn(),
  listKbCollections: vi.fn().mockResolvedValue({ data: { collections: [] } }),
  createKbCollection: vi.fn(),
  deleteKbCollection: vi.fn(),
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

import { createKbConfig, getKnowledgeNodes, searchKnowledge } from '@/api/modules/knowledge'

/** P0-2 分块样例：长文被切成 4 块，检索命中第 3 块 */
const CHUNKED_ITEM = {
  id: 'kid-1',
  knowledge_id: 'kid-1',
  title: 'Neurova 架构手册',
  category: 'tech',
  content: '第一章……第二章……第三章 内存系统……第四章……',
  visibility: 'private',
  owner_user_id: 'u-1',
  chunk_count: 4,
  chunk_hits: [
    { chunk_index: 2, content: '第三章 内存系统', score: 0.87 },
    { chunk_index: 0, content: '第一章', score: 0.12 },
  ],
}

const messages = {
  knowledge: {
    title: '知识库',
    remoteConfig: '远程配置',
    configName: '名称',
    configSource: '来源',
    configHasKey: '凭据已配',
    configId: '配置 ID',
    configCopyId: '复制 ID',
    configDelete: '删除',
    configCreate: '添加配置',
    configNamePlaceholder: '配置名称',
    configApiKey: 'API Key',
    configApiKeyPlaceholder: 'API Key（加密存储）',
    configAppId: 'App ID',
    configAppIdPh: '飞书开放平台自建应用 App ID',
    configAppSecret: 'App Secret',
    configAppSecretPh: 'App Secret（加密存储）',
    configBaseUrl: '服务地址',
    configBaseUrlIflowPh: '留空使用默认 https://platform.iflow.cn',
    configBaseUrlFeishuPh: '留空使用默认 https://open.feishu.cn',
    configBaseUrlImaPh: 'ima MCP 地址，如 http://localhost:9007/sse',
    configToken: 'Token',
    configTokenPh: 'Token（加密存储）',
    configDatasetId: '数据集 ID',
    configDatasetIdPh: '可选，数据集/集合 ID',
    configSpaceId: '知识空间 ID',
    configSpaceIdPh: '可选，限定单一知识空间',
    configApiUrl: 'API URL',
    configApiUrlPh: 'POST 端点，请求体 {query, dataset_id, top_k}',
    configKbId: '知识库 ID',
    configKbIdPh: '可选，ima 知识库 ID',
    configAllowLocal: '允许本地地址',
    configAllowLocalHint: 'ima 为本机服务时需开启',
    configFormIncomplete: '请填写名称与凭据',
    configMissingRequired: '请完整填写该类型的必填参数',
    collectionConfigPh: '选择配置',
    collectionNamePlaceholder: '集合名称',
    collectionCreate: '添加集合',
    chunkHit: '命中片段',
    chunkCount: '共 {count} 块',
    colTitle: '标题',
    colCategory: '分类',
    colVisibility: '可见性',
    colContent: '内容',
    colCreated: '创建时间',
    colActions: '操作',
    totalItems: '共 {total} 条',
    importTitle: '导入',
    importSuccess: '操作成功',
    importError: '操作失败',
    importUnsupported: '暂不支持该格式（旧版 .ppt/.doc/.xls 请先转存为新格式）',
    importParseFailed: '文件解析失败，未能抽取到文本',
    importBatchSuccess: '成功导入 {n} 个文件',
    importBatchPartial: '成功 {success} 个，失败 {fail} 个',
    importSkippedUnsupported: '已忽略 {n} 个不支持的文件',
    importTooManyFiles: '一次最多导入 {n} 个文件',
    dragOrClick: '拖拽',
    importFormats: '格式',
    importUrl: '导入网页',
    importUrlPlaceholder: 'URL',
    filterCategory: '分类',
    export: '导出',
    import: '导入',
    create: '新建',
  },
}

// a-table stub 不渲染 bodyCell slot（页面 slot 解构 column/record，
// 无 slot props 传入会崩）；本测试只验证创建表单，不需要表格内容
const stubs = {
  GlassPanel: { template: '<div><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  'a-table': {
    props: ['dataSource', 'columns'],
    template: `<div class="ant-table"><div v-for="r in dataSource || []" :key="r.id" class="ant-table-row" :data-id="r.id"><template v-for="c in columns || []" :key="c.key"><slot name="bodyCell" :column="c" :record="r" /></template></div></div>`,
  },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="ant-modal"><h3>{{ title }}</h3><slot/></div>' },
  'a-upload-dragger': { template: '<div><slot/></div>' },
  'a-divider': { template: '<hr />' },
  'a-input-search': { props: ['value', 'placeholder'], emits: ['update:value', 'search'], template: `<input class="ant-input-search" :value="value" :data-placeholder="placeholder" @input="$emit('update:value', $event.target.value)" @keyup.enter="$emit('search', value)" />` },
  'a-checkbox': { template: '<div />' },
  'a-radio-button': { template: '<div />' },
  'a-radio-group': { template: '<div />' },
  'a-input-password': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input-password" :data-placeholder="placeholder" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-input': { props: ['value', 'placeholder'], emits: ['update:value'], template: '<input class="ant-input" :data-placeholder="placeholder" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-select': { props: ['value', 'options', 'placeholder'], emits: ['update:value'], template: '<select class="ant-select" :value="value" @change="$emit(\'update:value\', $event.target.value)"><option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-switch': { props: ['checked'], emits: ['update:checked'], template: '<button class="ant-switch" @click="$emit(\'update:checked\', !checked)"></button>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="form-item" :data-label="label"><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(KnowledgePage, { global: { plugins: [i18n], stubs } })
}

async function openConfigModal(wrapper: ReturnType<typeof mountPage>) {
  const btn = wrapper.findAll('button').find((b) => b.text() === '远程配置')
  expect(btn, '页面须有「远程配置」入口按钮').toBeTruthy()
  await btn!.trigger('click')
  await flushPromises()
  return wrapper.find('.ant-modal')
}

async function setSourceType(wrapper: ReturnType<typeof mountPage>, value: string) {
  const select = wrapper.find('.ant-modal select.ant-select')
  expect(select.exists()).toBe(true)
  await select.setValue(value)
  await flushPromises()
}

function labeledInputs(wrapper: ReturnType<typeof mountPage>) {
  const labels = new Set<string>()
  wrapper.findAll('.ant-modal .form-item').forEach((el) => {
    const l = el.attributes('data-label')
    if (l) labels.add(l)
  })
  return labels
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('KnowledgePage 远程配置弹窗（分类型表单）', () => {
  it('默认 iflow：渲染 API Key + base_url + dataset_id', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await openConfigModal(wrapper)
    const labels = labeledInputs(wrapper)
    expect(labels.has('API Key'), 'iflow 须渲染 API Key').toBe(true)
    expect(labels.has('服务地址'), 'iflow 须渲染服务地址').toBe(true)
    expect(labels.has('数据集 ID'), 'iflow 须渲染数据集 ID').toBe(true)
    wrapper.unmount()
  })

  it('feishu：渲染 App ID / App Secret，不再显示通用 API Key 标签', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await openConfigModal(wrapper)
    await setSourceType(wrapper, 'feishu')
    const labels = labeledInputs(wrapper)
    expect(labels).toContain('App ID')
    expect(labels).toContain('App Secret')
    expect(labels, 'feishu 不应有通用 API Key 标签').not.toContain('API Key')
    expect(labels).toContain('知识空间 ID')
    wrapper.unmount()
  })

  it('ima：渲染服务地址 / Token / 知识库 ID / 本地地址开关', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await openConfigModal(wrapper)
    await setSourceType(wrapper, 'ima')
    const labels = labeledInputs(wrapper)
    expect(labels).toContain('服务地址')
    expect(labels).toContain('Token')
    expect(labels).toContain('知识库 ID')
    expect(wrapper.find('.ant-modal .ant-switch').exists()).toBe(true)
    wrapper.unmount()
  })

  it('custom：渲染 API URL + API Key（可选）+ dataset_id', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await openConfigModal(wrapper)
    await setSourceType(wrapper, 'custom')
    const labels = labeledInputs(wrapper)
    expect(labels).toContain('API URL')
    expect(labels).toContain('API Key')
    expect(labels).toContain('数据集 ID')
    wrapper.unmount()
  })

  it('feishu 提交：app_secret 走顶层 api_key（加密通道），其余进 settings', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const modal = await openConfigModal(wrapper)
    await setSourceType(wrapper, 'feishu')

    const inputs = modal.findAll('input.ant-input')
    // 顺序：名称 → App ID → 服务地址 → 空间 ID（密码框单独定位）
    await inputs[0].setValue('我的飞书库')
    await inputs[1].setValue('cli_123')
    await modal.find('input.ant-input-password').setValue('sh-secret')
    await inputs[2].setValue('https://open.feishu.cn')
    await inputs[3].setValue('741953')

    const createBtn = modal.findAll('button').find((b) => b.text().includes('添加配置'))
    await createBtn!.trigger('click')
    await flushPromises()

    expect(createKbConfig, '必填齐全时应调用创建接口').toHaveBeenCalledTimes(1)
    const payload = vi.mocked(createKbConfig).mock.calls[0][0] as Record<string, any>
    expect(payload.name).toBe('我的飞书库')
    expect(payload.source_type).toBe('feishu')
    expect(payload.api_key, 'App Secret 走后端加密存储通道').toBe('sh-secret')
    expect(payload.settings).toEqual(
      expect.objectContaining({ app_id: 'cli_123', base_url: 'https://open.feishu.cn', space_id: '741953' }),
    )
    wrapper.unmount()
  })

  it('ima 提交：token 走顶层 api_key，allow_local 进 settings；base_url 必填缺失不提交', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const modal = await openConfigModal(wrapper)
    await setSourceType(wrapper, 'ima')

    const inputs = modal.findAll('input.ant-input')
    // 名称 → 服务地址 → 知识库 ID（Token 为密码框）
    await inputs[0].setValue('本机 ima')
    await modal.find('input.ant-input-password').setValue('tok-9')

    const createBtn = modal.findAll('button').find((b) => b.text().includes('添加配置'))
    await createBtn!.trigger('click')
    await flushPromises()
    expect(createKbConfig, 'base_url 必填缺失时不得提交').not.toHaveBeenCalled()

    await inputs[1].setValue('http://localhost:9007/sse')
    await createBtn!.trigger('click')
    await flushPromises()
    expect(createKbConfig).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(createKbConfig).mock.calls[0][0] as Record<string, any>
    expect(payload.api_key).toBe('tok-9')
    expect(payload.settings).toEqual(
      expect.objectContaining({ base_url: 'http://localhost:9007/sse', allow_local: false }),
    )
    wrapper.unmount()
  })

  it('类型切换重置残留凭据：iflow 填的 API Key 不带入 custom 提交', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const modal = await openConfigModal(wrapper)

    await modal.findAll('input.ant-input')[0].setValue('混合库')
    await modal.find('input.ant-input-password').setValue('sk-iflow')
    await setSourceType(wrapper, 'custom')

    const inputs = modal.findAll('input.ant-input')
    // custom 表单：名称 → API URL → 数据集 ID（API Key 为密码框且已重置）
    await inputs[1].setValue('https://kb.example/retrieve')
    const createBtn = modal.findAll('button').find((b) => b.text().includes('添加配置'))
    await createBtn!.trigger('click')
    await flushPromises()

    expect(createKbConfig).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(createKbConfig).mock.calls[0][0] as Record<string, any>
    expect(payload.source_type).toBe('custom')
    expect(payload.api_key, '切换类型后上一类型的凭据不得残留').toBeUndefined()
    expect(payload.settings).toEqual(expect.objectContaining({ api_url: 'https://kb.example/retrieve' }))
    wrapper.unmount()
  })
})

// ══════════════════════════════════════════════════════════════
// P0-2 RAG 分块 — 前端块级溯源展示（防回归）
//
// 背景（2026-09-03）：后端 88ae8ec3 已落「摄取即分块 + 检索块级溯源」
// 契约（chunk_count / chunk_hits[{chunk_index, content, score}]），但
// KnowledgePage 从未消费；且普通搜索把 q 发给 GET /knowledge（后端
// 忽略该参数）——真正带块级溯源的 POST /knowledge/search 已 import
// 却从未调用。
//
// 契约（防回归）：
// 1. 关键词搜索走 searchKnowledge（POST /knowledge/search），不再发
//    GET q 参数（后端列表端点忽略 q，属断链）。
// 2. 列表渲染块数标签（chunk_count > 1 时）。
// 3. 有 chunk_hits 的条目渲染「命中片段」明细（块序号 + 片段正文）。
// ══════════════════════════════════════════════════════════════
describe('KnowledgePage P0-2 分块溯源展示', () => {
  it('关键词搜索走 POST /knowledge/search（带块级溯源的端点），不走 GET q 断链', async () => {
    vi.mocked(searchKnowledge).mockResolvedValue({ data: [CHUNKED_ITEM] } as any)
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)

    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getKnowledgeNodes).mockClear()

    const input = wrapper.find('input.ant-input-search')
    expect(input.exists(), '页面须有搜索框').toBe(true)
    await input.setValue('内存系统')
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(searchKnowledge, '关键词搜索须调 POST /knowledge/search').toHaveBeenCalledTimes(1)
    const [query, params] = vi.mocked(searchKnowledge).mock.calls[0]
    expect(query).toBe('内存系统')
    expect(params).toEqual(expect.objectContaining({ agent_id: 'default', scope: 'all' }))
    expect(getKnowledgeNodes, '搜索时不得回退到 GET /knowledge?q= 断链').not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('无搜索词时仍走 GET 列表端点（分页浏览语义）', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)

    const wrapper = mountPage()
    await flushPromises()

    expect(getKnowledgeNodes).toHaveBeenCalledTimes(1)
    expect(searchKnowledge).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('列表渲染块数标签：chunk_count > 1 显示「共 N 块」', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [CHUNKED_ITEM], total: 1 } } as any)

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.find('.ant-table').text()
    expect(text).toContain('共 4 块')
    wrapper.unmount()
  })

  it('列表渲染命中片段：块序号 + 片段正文按得分降序', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [CHUNKED_ITEM], total: 1 } } as any)

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.find('.ant-table').text()
    expect(text).toContain('命中片段')
    expect(text).toContain('#3')
    expect(text).toContain('第三章 内存系统')
    wrapper.unmount()
  })

  it('单块（chunk_count=1）与无 chunk_hits 时不渲染块级明细', async () => {
    const single = { ...CHUNKED_ITEM, id: 'kid-2', knowledge_id: 'kid-2', chunk_count: 1, chunk_hits: [] }
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [single], total: 1 } } as any)

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.find('.ant-table').text()
    expect(text).not.toContain('共 1 块')
    expect(text).not.toContain('命中片段')
    wrapper.unmount()
  })
})

describe('KnowledgePage 文件导入（批量契约）', () => {
  function makeFile(name: string) {
    return new File(['x'], name)
  }

  it('多选批量上传：2 个文件依次上传，全部成功弹批量成功提示并刷新', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)
    const { request } = await import('@/api')
    vi.mocked(request.post).mockResolvedValue({
      code: 0, message: 'Import completed',
      data: { items: [{ knowledge_id: 'k1', title: 't', content: 'x' }] },
    } as any)

    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getKnowledgeNodes).mockClear()
    const vm = wrapper.vm as any
    await vm.beforeImportUpload(makeFile('a.pptx'))
    await vm.beforeImportUpload(makeFile('b.docx'))
    expect(vm.importFiles).toHaveLength(2)
    await vm.handleImport()
    await flushPromises()

    expect(request.post).toHaveBeenCalledTimes(2)
    expect(message.success).toHaveBeenCalledTimes(1)
    expect(vi.mocked(message.success).mock.calls[0][0]).toContain('2 个')
    expect(getKnowledgeNodes, '有成功须刷新列表').toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('文件夹上传：不支持的文件入队时被过滤并计数，不上传', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.beforeImportUpload(makeFile('doc1.docx'))
    await vm.beforeImportUpload(makeFile('photo.exe'))
    await vm.beforeImportUpload(makeFile('doc2.pdf'))
    expect(vm.importFiles, '不支持的扩展名不得入队').toHaveLength(2)
    expect(vm.importSkipped).toBe(1)
    wrapper.unmount()
  })

  it('部分失败：成功 1 失败 1 弹批量部分提示，仍刷新列表', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)
    const { request } = await import('@/api')
    vi.mocked(request.post)
      .mockResolvedValueOnce({ code: 0, message: 'ok', data: { items: [{ knowledge_id: 'k1' }] } } as any)
      .mockResolvedValueOnce({ code: 1, message: 'extract_failed:unsupported_format', data: { items: [], status: 'unsupported_format' } } as any)

    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getKnowledgeNodes).mockClear()
    const vm = wrapper.vm as any
    await vm.beforeImportUpload(makeFile('ok.txt'))
    await vm.beforeImportUpload(makeFile('scanned.pdf'))
    await vm.handleImport()
    await flushPromises()

    expect(message.warning).toHaveBeenCalledTimes(1)
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('成功 1 个')
    expect(getKnowledgeNodes, '部分成功也要刷新').toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('全部失败：不弹成功、不刷新列表，错误信息含失败原因', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ data: { items: [], total: 0 } } as any)
    const { request } = await import('@/api')
    vi.mocked(request.post).mockResolvedValue({
      code: 1, message: 'extract_failed:unsupported_format',
      data: { items: [], status: 'unsupported_format' },
    } as any)

    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getKnowledgeNodes).mockClear()
    const vm = wrapper.vm as any
    await vm.beforeImportUpload(makeFile('scanned.pdf'))
    await vm.handleImport()
    await flushPromises()

    expect(message.success, '失败不得提示导入成功').not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledTimes(1)
    expect(vi.mocked(message.error).mock.calls[0][0]).toContain('不支持')
    expect(getKnowledgeNodes, '无成功不得刷新列表').not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import FilePage from '@/pages/FilePage.vue'

/**
 * P1-22（审计 2026-11-16）：FilePage「打开」按钮把 ref 当函数调用——
 * 模板 `@click="previewFile(record)"` 里 previewFile 是 ref（恒 null），
 * 真实现叫 previewFileFn 且全文件零引用。点击必抛 TypeError，预览全废。
 *
 * 同页同根因（信封/裸形状错位，axios 拦截器已解包）：
 * - fetchFiles 读 `res?.data` → 后端 GET /files 是裸数组 → 列表恒空；
 * - showHistory 读 `res?.data ?? []` → 后端 versions 是 {code,data:{versions}} 信封
 *   → 拿到对象而非数组，历史弹窗渲染垃圾。
 *
 * mock 用**归一后的模块形状**（listFiles→FileItem[]，getFileVersions→信封原样）。
 */
vi.mock('@/api/modules/files', () => ({
  listFiles: vi.fn(),
  uploadFile: vi.fn(),
  getFileContent: vi.fn(),
  getFileVersions: vi.fn(),
  deleteFile: vi.fn(),
  downloadFile: vi.fn(),
  getFilePreview: vi.fn(),
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})

import { listFiles, getFileContent, getFileVersions, getFilePreview } from '@/api/modules/files'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': {
      system: { files: '文件' },
      common: {
        upload: '上传', open: '打开', download: '下载', delete: '删除',
        noData: '暂无数据', error: '操作失败', createdAt: '创建时间', type: '类型',
        name: '名称', actions: '操作', confirm: '确认',
      },
      file: {
        totalStorage: '总存储', usedStorage: '已用', size: '大小', version: '版本',
        history: '历史', versionHistory: '版本历史',
      },
      agent: { deleteConfirm: '确认删除？' },
    },
  },
  globalInjection: true,
})

const tableStub = {
  props: ['dataSource'],
  template: `<div class="stub-table">
    <div v-for="row in dataSource || []" :key="row.id" class="stub-row">
      <span class="cell-name"><slot name="bodyCell" :column="{ key: 'name' }" :record="row" /></span>
      <span class="cell-size"><slot name="bodyCell" :column="{ key: 'size' }" :record="row" /></span>
      <span class="cell-version"><slot name="bodyCell" :column="{ key: 'version' }" :record="row" /></span>
      <span class="cell-created_at"><slot name="bodyCell" :column="{ key: 'created_at' }" :record="row" /></span>
      <span class="cell-actions"><slot name="bodyCell" :column="{ key: 'actions' }" :record="row" /></span>
    </div>
  </div>`,
}

const globalStubs = {
  GlassCard: { template: '<div><slot/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="nr-glass-btn" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-upload': { template: '<div><slot/></div>' },
  'a-progress': { template: '<div/>' },
  'a-table': tableStub,
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot/></div>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-timeline': { template: '<div><slot/></div>' },
  'a-timeline-item': { template: '<div class="stub-timeline-item"><slot/></div>' },
}

function mountFilePage() {
  return mount(FilePage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  // jsdom 没有 createObjectURL（图片预览接线用）
  URL.createObjectURL = vi.fn(() => 'blob:mock-preview') as any
  URL.revokeObjectURL = vi.fn() as any
  vi.mocked(listFiles).mockResolvedValue([
    { id: 'f1', name: 'a.txt', type: 'text', size: 3, created_at: 1700000000 },
    { id: 'f2', name: 'pic.png', type: 'image', size: 99, created_at: 1700000001 },
  ] as any)
  vi.mocked(getFileContent).mockResolvedValue('hello file' as any)
  vi.mocked(getFileVersions).mockResolvedValue({
    code: 0,
    data: { versions: [{ version: '1.0.0', created_at: 1700000000 }] },
  } as any)
  vi.mocked(getFilePreview).mockResolvedValue(new Blob(['img']) as any)
})

describe('FilePage — 列表契约与预览链（P1-22）', () => {
  it('列表按后端裸数组渲染（file_id→id 归一后行可见）', async () => {
    const wrapper = mountFilePage()
    await flushPromises()
    expect(listFiles).toHaveBeenCalled()
    expect(wrapper.text()).toContain('a.txt')
    expect(wrapper.text()).toContain('pic.png')
  })

  it('点击「打开」打开文本预览并按真实 id 取内容', async () => {
    const wrapper = mountFilePage()
    await flushPromises()

    const openBtn = wrapper.findAll('button').find((b) => b.text().includes('打开'))
    expect(openBtn, '「打开」按钮应随列表行渲染').toBeTruthy()

    await openBtn!.trigger('click')
    await flushPromises()

    expect(getFileContent).toHaveBeenCalledWith('f1')
    expect(wrapper.text()).toContain('hello file')
  })

  it('图片类型走 /preview blob 接线（后端 GET /files/{id}/preview 的消费者）', async () => {
    const wrapper = mountFilePage()
    await flushPromises()

    const rows = wrapper.findAll('.stub-row')
    const imgRow = rows.find((r) => r.text().includes('pic.png'))
    expect(imgRow).toBeTruthy()
    const imgOpenBtn = imgRow!.findAll('button').find((b) => b.text().includes('打开'))
    expect(imgOpenBtn).toBeTruthy()

    await imgOpenBtn!.trigger('click')
    await flushPromises()

    expect(getFilePreview).toHaveBeenCalledWith('f2')
    expect(wrapper.find('.preview-image img').exists()).toBe(true)
    expect((wrapper.find('.preview-image img').element as HTMLImageElement).getAttribute('src')).toBe('blob:mock-preview')
  })

  it('版本历史弹窗解出 {code,data:{versions}} 信封里的数组', async () => {
    const wrapper = mountFilePage()
    await flushPromises()

    const historyBtn = wrapper.findAll('button').find((b) => b.text().includes('历史'))
    expect(historyBtn).toBeTruthy()
    await historyBtn!.trigger('click')
    await flushPromises()

    expect(getFileVersions).toHaveBeenCalledWith('f1')
    expect(wrapper.text()).toContain('v1.0.0')
  })
})

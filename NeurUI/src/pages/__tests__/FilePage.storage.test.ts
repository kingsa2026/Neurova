import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import FilePage from '@/pages/FilePage.vue'

/**
 * 存储卡接真实读数（S6 移交·用户拍板 2026-11-17）：
 * - 后端 `GET /files/storage/info` 返回**裸** `StorageInfo{user_id,total_files,total_size,by_type}`
 *   （files_api.py:81，无配额语义）；
 * - 存储卡此前挂零数据源，且带配额进度条（`storagePercent` + a-progress）——后端没有
 *   配额语义，那是装饰读数；
 * - 拍板：接真实总量/已用，配额进度条退役；拉取失败诚实显示「暂无数据」而非恒 0。
 */
vi.mock('@/api/modules/files', () => ({
  listFiles: vi.fn(),
  uploadFile: vi.fn(),
  getFileContent: vi.fn(),
  getFileVersions: vi.fn(),
  deleteFile: vi.fn(),
  downloadFile: vi.fn(),
  getFilePreview: vi.fn(),
  getStorageInfo: vi.fn(),
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})

import { getStorageInfo, listFiles } from '@/api/modules/files'

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
        totalFiles: '文件总数', usedStorage: '已用', size: '大小',
        version: '版本', history: '历史', versionHistory: '版本历史',
      },
      agent: { deleteConfirm: '确认删除？' },
    },
  },
  globalInjection: true,
})

const globalStubs = {
  GlassCard: { template: '<div class="glass-card"><slot/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="nr-glass-btn" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-upload': { template: '<div><slot/></div>' },
  'a-progress': { template: '<div class="stub-progress"/>' },
  'a-table': { template: '<div class="stub-table"/>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot/></div>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-timeline': { template: '<div><slot/></div>' },
  'a-timeline-item': { template: '<div><slot/></div>' },
}

function mountFilePage() {
  return mount(FilePage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

const SOURCE = readFileSync(resolve(process.cwd(), 'src/pages/FilePage.vue'), 'utf-8')

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listFiles).mockResolvedValue([] as any)
  vi.mocked(getStorageInfo).mockResolvedValue({
    user_id: 'u1',
    total_files: 1234,
    total_size: 2048,
    by_type: { text: 2 },
  } as any)
})

describe('FilePage — 存储卡接真实读数（S6 移交）', () => {
  it('挂载后拉取 /files/storage/info 并渲染真实 total_files/total_size', async () => {
    const wrapper = mountFilePage()
    await flushPromises()

    expect(getStorageInfo).toHaveBeenCalled()
    const card = wrapper.find('.storage-info')
    expect(card.exists(), '存储卡应存在').toBeTruthy()
    // U1 拍板口径修正：total_files 是**文件数**，渲染纯数字（1,234 个），
    // 不得过 formatBytes——把 1234 个文件显示成「1.2 KB」是装饰读数。
    expect(card.text()).toContain('1234')
    expect(card.text()).not.toContain('1.2 KB')
    expect(card.text()).toContain('文件总数')
    expect(card.text()).toContain('2.0 KB')
  })

  it('文件数读数不过 formatBytes（语义错位钉死在源码层）', () => {
    expect(SOURCE).not.toContain('formatBytes(storageInfo.total')
  })

  it('配额进度条装饰退役（后端无配额语义）', () => {
    expect(SOURCE).not.toContain('a-progress')
    expect(SOURCE).not.toContain('storagePercent')
  })

  it('拉取失败诚实显示暂无数据，而非恒 0 假读数', async () => {
    vi.mocked(getStorageInfo).mockRejectedValue(new Error('storage unavailable'))
    const wrapper = mountFilePage()
    await flushPromises()

    const card = wrapper.find('.storage-info')
    expect(card.exists()).toBeTruthy()
    expect(card.text()).toContain('暂无数据')
  })
})

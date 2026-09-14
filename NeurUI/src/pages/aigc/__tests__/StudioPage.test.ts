/**
 * StudioPage（R4 项目列表）契约：新建项目跳转、列表渲染、删除。
 * 创作专区 = 项目化四 Phase 工作台入口（对标 huobao 项目管理）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return { ...actual, useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: {}, path: '/aigc/studio' }) }
})
vi.mock('@/api/modules/studio', () => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn().mockResolvedValue({}),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import StudioPage from '@/pages/aigc/StudioPage.vue'
import { listProjects, createProject } from '@/api/modules/studio'

const listMock = listProjects as unknown as ReturnType<typeof vi.fn>
const createMock = createProject as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const PROJECT = {
  id: 'p1', owner_user_id: 'u1', title: '赘婿龙王', description: '三年之期', genre: '战神归来',
  style: 'cinematic', aspect_ratio: '9:16 竖屏', total_episodes: 1, status: 'draft',
  thumbnail: '', created_at: 1757700000, updated_at: 1757700100,
}

const mountPage = () =>
  mount(StudioPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { template: '<div><slot /></div>' },
        GlassButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-empty': { template: '<div><slot /></div>' },
        'a-modal': { template: '<div><slot /></div>' },
        'a-form': { template: '<div><slot /></div>' },
        'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
        'a-input': { props: ['value'], template: '<input />' },
        'a-input-number': { template: '<input />' },
        'a-select': { props: ['options'], template: '<select />' },
        'a-tag': { template: '<span><slot /></span>' },
        'a-popconfirm': { props: ['title'], template: '<div><slot /></div>' },
      },
    },
  })

describe('StudioPage（项目列表）', () => {
  beforeEach(() => {
    listMock.mockReset()
    listMock.mockResolvedValue({ code: 0, data: { projects: [PROJECT] } })
    createMock.mockReset()
  })

  it('挂载拉取并渲染项目卡片', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalled()
    expect(wrapper.text()).toContain('赘婿龙王')
    expect(wrapper.text()).toContain('战神归来')
  })

  it('新建项目成功后跳转工作台', async () => {
    createMock.mockResolvedValue({ code: 0, data: { project: { ...PROJECT, id: 'p2' } } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.form = { ...vm.form, title: '新项目' }
    await vm.create()
    expect(createMock).toHaveBeenCalledWith(expect.objectContaining({ title: '新项目' }))
  })

  it('空列表显示空态', async () => {
    listMock.mockResolvedValue({ code: 0, data: { projects: [] } })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).not.toContain('赘婿龙王')
  })
})

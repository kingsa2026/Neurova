/**
 * AIGC 二级菜单渲染契约（2026-09-16 用户决策）
 *
 * 背景: 「模型与工具」下拉原为 8 个平铺项，其中 文本生成/图片生成/音频生成/
 * 视频生成/创作专区 五个 AIGC 页收拢为「AIGC工具」二级菜单组。
 *
 * 契约:
 *  1. 五个 AIGC 子页渲染在 .nr-glass-submenu-panel 面板内，路由与顺序不变。
 *  2. 组头（.nr-glass-dropdown-group）不是导航链接，仅悬停展开子项。
 *  3. 当前路由命中任一子项时，组头与「模型与工具」分类同时高亮。
 *  4. 权限过滤作用于子项：部分授权只渲染允许项；全部拒绝则整组隐藏。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

let routePath = '/aigc/text'
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ path: routePath }),
    useRouter: () => ({ push: vi.fn() }),
  }
})

let mockUser: Record<string, unknown> | null = { username: 'u1', role: 'user', allowed_modules: [] }
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ get user() { return mockUser } }),
}))

import TopNavMenu from '../TopNavMenu.vue'

const RouterLinkStub = {
  name: 'RouterLink',
  props: ['to'],
  template: '<a class="topnav-link" :data-to="to"><slot /></a>',
}

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh-CN',
    messages: {
      'zh-CN': {
        nav: {
          globalNav: '全局导航', dashboard: '总览',
          modelTools: '模型与工具', opsMonitor: '运维监控',
          platformAdmin: '平台管理', platformService: '平台服务',
          models: '模型服务', toolLayers: '工具层', sandbox: '沙箱',
          aigcTools: 'AIGC工具', aigcText: '文本生成', aigcImage: '图片生成',
          aigcAudio: '音频生成', aigcVideo: '视频生成', aigcStudio: '创作专区',
        },
      },
    },
  })
}

function mountMenu() {
  return mount(TopNavMenu, {
    global: {
      plugins: [makeI18n()],
      components: { RouterLink: RouterLinkStub },
      stubs: {
        'a-dropdown': { template: '<div class="topnav-cat"><slot /><slot name="overlay" /></div>' },
      },
    },
  })
}

describe('TopNavMenu AIGC 二级菜单', () => {
  it('五个 AIGC 子页渲染在子菜单面板内，组头不是链接', () => {
    const wrapper = mountMenu()
    const submenu = wrapper.find('.nr-glass-dropdown-submenu')
    expect(submenu.exists(), '缺少 AIGC 二级菜单组').toBe(true)
    const panel = submenu.find('.nr-glass-submenu-panel')
    expect(panel.exists()).toBe(true)
    expect(panel.findAll('.topnav-link').map(a => a.attributes('data-to'))).toEqual([
      '/aigc/text', '/aigc/image', '/aigc/audio', '/aigc/video', '/aigc/studio',
    ])
    // 组头是纯标签：无 data-to，不在任何 router-link 内
    const group = submenu.find('.nr-glass-dropdown-group')
    expect(group.exists()).toBe(true)
    expect(group.text()).toContain('AIGC工具')
    expect(group.attributes('data-to')).toBeUndefined()
    // 一级下拉面板里不再平铺 AIGC 链接
    const topLinks = wrapper.findAll('.nr-glass-dropdown > .topnav-link')
      .map(a => a.attributes('data-to'))
    expect(topLinks).not.toContain('/aigc/text')
  })

  it('当前路由命中子项时，组头与所属分类同时高亮', () => {
    routePath = '/aigc/audio'
    const wrapper = mountMenu()
    expect(wrapper.find('.nr-glass-dropdown-group').classes()).toContain('is-active')
    const activeCat = wrapper.findAll('.nr-topnav-cat.is-active').map(n => n.text())
    expect(activeCat.some(txt => txt.includes('模型与工具'))).toBe(true)
    routePath = '/aigc/text'
  })

  it('部分授权：子项按 allowed_modules 过滤，组仍显示', () => {
    mockUser = { username: 'u1', role: 'user', allowed_modules: ['/aigc/image'] }
    const wrapper = mountMenu()
    const panel = wrapper.find('.nr-glass-submenu-panel')
    expect(panel.exists()).toBe(true)
    expect(panel.findAll('.topnav-link').map(a => a.attributes('data-to'))).toEqual(['/aigc/image'])
    mockUser = { username: 'u1', role: 'user', allowed_modules: [] }
  })

  it('全部子项被拒时整组隐藏', () => {
    mockUser = { username: 'u1', role: 'user', allowed_modules: ['/models'] }
    const wrapper = mountMenu()
    expect(wrapper.find('.nr-glass-dropdown-submenu').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('AIGC工具')
    mockUser = { username: 'u1', role: 'user', allowed_modules: [] }
  })
})

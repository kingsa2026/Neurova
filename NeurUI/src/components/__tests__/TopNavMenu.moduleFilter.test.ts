/**
 * 顶部导航按用户组过滤测试
 *
 * 契约:
 *  1. 无限制用户（allowed_modules 空）→ 4 组全渲染。
 *  2. 受限用户 → 组内未授权项被过滤；组内全部被过滤则整组隐藏。
 *  3. admin 恒全量。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ path: '/dashboard' }),
    useRouter: () => ({ push: vi.fn() }),
  }
})

// 可变 auth 用户：每个用例先改 mockUser 再挂载
let mockUser: Record<string, unknown> | null = { username: 'u1', role: 'user' }
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ get user() { return mockUser } }),
}))

import { default as TopNavMenu } from '../TopNavMenu.vue'
import { TOP_NAV_CATEGORIES } from '@/config/navigation'

// 模板中的 <router-link> 按全局注册组件解析（与 NavigationZones.test.ts 同法）
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
          globalNav: '全局导航',
          dashboard: '总览',
          modelTools: '模型与工具', opsMonitor: '运维监控',
          platformAdmin: '平台管理', platformService: '平台服务',
          models: '模型服务', toolLayers: '工具层', sandbox: '沙箱',
          monitor: '资源监控', health: '健康检查', logs: '日志', stats: '统计',
          settings: '系统设置', voiceTranscription: '语音转写', memorySettings: '记忆设置',
          enhancedusers: '增强用户', groups: '用户组', firewall: '防火墙', audit: '审计',
          marketplace: '市场管理', benchmark: '基准测试',
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

describe('TopNavMenu 用户组过滤', () => {
  it('无限制用户：4 组全部渲染（快捷入口 + 16 个菜单项）', () => {
    mockUser = { username: 'u1', role: 'user', allowed_modules: [] }
    const wrapper = mountMenu()
    const links = wrapper.findAll('.topnav-link').map(a => a.attributes('data-to'))
    const expected = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to)).concat(['/dashboard'])
    expect(links.sort()).toEqual(expected.sort())
  })

  it('受限用户：未授权项被过滤，空组隐藏', () => {
    mockUser = { username: 'u1', role: 'user', allowed_modules: ['/models', '/health'] }
    const wrapper = mountMenu()
    const links = wrapper.findAll('.topnav-link').map(a => a.attributes('data-to'))
    expect(links).toContain('/models')
    expect(links).toContain('/health')
    expect(links).not.toContain('/tool-layers')
    expect(links).not.toContain('/settings')
    expect(links).not.toContain('/benchmark')
  })

  it('admin 恒全量', () => {
    mockUser = { username: 'root', role: 'admin', allowed_modules: [] }
    const wrapper = mountMenu()
    const links = wrapper.findAll('.topnav-link').map(a => a.attributes('data-to'))
    const expected = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to)).concat(['/dashboard'])
    expect(links.sort()).toEqual(expected.sort())
  })
})

/**
 * 三区导航结构测试 — Agent 区 / 用户区 / 系统配置区
 *
 * 行为契约:
 *  1. 顶部导航（系统配置区）收敛为固定 4 组（模型与工具/运维监控/平台管理/平台服务），
 *     全局路由引用不得重复（如 /models 双入口回归即红）。
 *  2. 导航配置中出现的每一个路由路径都必须真实存在于路由表，
 *     防止「菜单指向幽灵路由」回归。
 *  3. GlassNavGroup 可折叠分组：展开/收起切换 + localStorage 持久化；
 *     侧栏折叠态退化为「图标直达第一个子项」。
 *  4. AgentPageTabs 成对页面页内 tab：渲染全部 tab，当前路由高亮。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ path: '/agent/a1/sleep/status' }),
    useRouter: () => ({ push: vi.fn() }),
    RouterLink: {
      name: 'RouterLink',
      props: ['to'],
      template: '<a :data-to="to"><slot /></a>',
    },
  }
})

import { TOP_NAV_CATEGORIES } from '@/config/navigation'
import GlassNavGroup from '../GlassNavGroup.vue'
import AgentPageTabs from '../AgentPageTabs.vue'
import router from '@/router'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import deDE from '@/i18n/locales/de-DE'
import frFR from '@/i18n/locales/fr-FR'
import esES from '@/i18n/locales/es-ES'
import itIT from '@/i18n/locales/it-IT'
import ruRU from '@/i18n/locales/ru-RU'
import hiIN from '@/i18n/locales/hi-IN'
import arSA from '@/i18n/locales/ar-SA'

const ALL_LOCALES: Record<string, any> = {
  'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR,
  'de-DE': deDE, 'fr-FR': frFR, 'es-ES': esES, 'it-IT': itIT,
  'ru-RU': ruRU, 'hi-IN': hiIN, 'ar-SA': arSA,
}

describe('侧栏导航 i18n 完整性', () => {
  // MainLayout 三区导航实际引用的 nav 分组/条目键
  const NAV_KEYS_IN_MAINLAYOUT = [
    'knowledgeCognition', 'agentCapabilities', 'agentRuntime',
    'userZone', 'collaboration', 'skillMarket', 'skillPool',
  ]

  it('nav 分组键在全部 11 个语言包存在（缺失即渲染原始键名回归）', () => {
    for (const [locale, msgs] of Object.entries(ALL_LOCALES)) {
      const nav = msgs?.nav ?? {}
      for (const key of NAV_KEYS_IN_MAINLAYOUT) {
        expect(nav[key], `${locale}.nav.${key} 缺失`).toBeTruthy()
      }
    }
  })
})

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh-CN',
    messages: {
      'zh-CN': {
        nav: { knowledgeCognition: '知识与认知', sleepstatus: '状态', sleepsettings: '设置' },
      },
    },
  })
}

describe('顶部导航（系统配置区）', () => {
  it('收敛为固定 4 组', () => {
    expect(TOP_NAV_CATEGORIES.map(c => c.key)).toEqual([
      'modelTools', 'opsMonitor', 'platformAdmin', 'platformService',
    ])
  })

  it('组内路由引用零重复（/models 等双入口回归即红）', () => {
    const all = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to))
    const dup = all.filter((to, i) => all.indexOf(to) !== i)
    expect(dup).toEqual([])
  })

  it('每个菜单目标都能命中真实路由', () => {
    const all = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to))
    for (const to of all) {
      expect(router.resolve(to).matched.length, `路由不存在: ${to}`).toBeGreaterThan(0)
    }
  })

  it('用户级功能页（知识库/AIGC/协作）不得回流到系统配置区', () => {
    const all = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to))
    for (const banned of ['/knowledge', '/aigc', '/collaboration/hub', '/neuron', '/skill-pool', '/chat', '/channels', '/notifications']) {
      expect(all, `${banned} 属用户区，不应出现在顶部`).not.toContain(banned)
    }
  })
})

describe('GlassNavGroup 可折叠分组', () => {
  beforeEach(() => localStorage.clear())

  function mountGroup(props: Record<string, unknown> = {}) {
    return mount(GlassNavGroup, {
      props: {
        labelKey: 'nav.knowledgeCognition',
        storageKey: 'test-group',
        firstItemTo: '/agent/a1/memory',
        count: 2,
        ...props,
      },
      slots: { default: '<div class="child">c1</div>' },
      global: {
        plugins: [makeI18n()],
        components: {
          RouterLink: {
            name: 'RouterLink',
            props: ['to'],
            template: '<a :data-to="to"><slot /></a>',
          },
        },
      },
    })
  }

  it('默认收起，点击标题展开子项，再点收起', async () => {
    const wrapper = mountGroup()
    expect(wrapper.find('.child').exists()).toBe(false)
    await wrapper.find('.nr-nav-group-head').trigger('click')
    expect(wrapper.find('.child').exists()).toBe(true)
    await wrapper.find('.nr-nav-group-head').trigger('click')
    expect(wrapper.find('.child').exists()).toBe(false)
  })

  it('展开状态持久化到 localStorage，重挂载后保持展开', async () => {
    const wrapper = mountGroup()
    await wrapper.find('.nr-nav-group-head').trigger('click')
    expect(localStorage.getItem('nr-nav-group-test-group')).toBe('true')

    const remounted = mountGroup()
    expect(remounted.find('.child').exists()).toBe(true)
  })

  it('侧栏折叠态：隐藏标题，渲染直达第一个子项的图标链接', () => {
    const wrapper = mountGroup({ collapsed: true })
    expect(wrapper.find('.nr-nav-group-head').exists()).toBe(false)
    const link = wrapper.find('.nr-nav-group-collapsed-link')
    expect(link.exists()).toBe(true)
    expect(link.attributes('data-to')).toBe('/agent/a1/memory')
  })
})

describe('AgentPageTabs 成对页面页内 tab', () => {
  function mountTabs() {
    return mount(AgentPageTabs, {
      props: {
        tabs: [
          { labelKey: 'nav.sleepstatus', to: '/agent/a1/sleep/status' },
          { labelKey: 'nav.sleepsettings', to: '/agent/a1/sleep/settings' },
        ],
      },
      global: { plugins: [makeI18n()] },
    })
  }

  it('渲染全部 tab 链接', () => {
    const wrapper = mountTabs()
    const links = wrapper.findAll('.nr-page-tab')
    expect(links.length).toBe(2)
    expect(links[0].text()).toBe('状态')
    expect(links[1].text()).toBe('设置')
  })

  it('当前路由对应的 tab 高亮', () => {
    const wrapper = mountTabs()
    expect(wrapper.findAll('.nr-page-tab')[0].classes()).toContain('is-active')
    expect(wrapper.findAll('.nr-page-tab')[1].classes()).not.toContain('is-active')
  })
})

// flushPromises 保持 import 使用，避免 lint 报未使用
void flushPromises

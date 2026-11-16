/**
 * 3.6-5 审计收口（R5）：L0 网关设置 / L1 隔离开关 / L2 保护路径三块
 * 本地硬编码装饰态。
 * - L2 保护路径：旧实现前端编造 10 条（通配 env/ssh 等假条目），后端
 *   GlobalRuleSet 的真实清单（/firewall/blocked → blocked_paths）存在却
 *   未消费——接真实数据。
 * - L1 隔离开关：旧实现 a-switch 只翻本地 reactive（无任何后端效果，假交互）
 *   ——退役开关，改「内置」标注（UserRuleSet.agent_isolation 内建启用）。
 * - L0 网关校验/净化：引擎内建能力（max_input_length / sensitive_output_patterns
 *   驱动），非可翻转开关——「已启用/已禁用」假状态改「内置」标注。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const requestGet = vi.fn((url: string) => {
  if (url === '/firewall/blocked') {
    return Promise.resolve({ code: 0, data: { blocked_ips: ['10.0.0.5'], blocked_paths: ['/etc/passwd', '/etc/shadow', '/root'] } })
  }
  if (url === '/firewall/stats') return Promise.resolve({ code: 0, data: {} })
  return Promise.resolve([])
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { agentId: 'kai' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api', () => {
  const apiFace = {
    get: (...args: unknown[]) => requestGet(...(args as [string])),
    post: vi.fn(), put: vi.fn(), delete: vi.fn(),
  }
  return {
    default: apiFace,
    request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
    // firewall.ts 走 default 门面的 api.get；页面 fetchBlocked 原样消费其解包结果
    api: apiFace,
  }
})

import AgentFirewallPage from '../AgentFirewallPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const stubs = {
  'a-empty': { template: '<div class="empty"/>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div><slot/></div>' },
  'a-input': { template: '<input/>' },
  'a-modal': { props: ['open'], template: '<div v-if="open"><slot/></div>' },
  'a-popconfirm': { template: '<div><slot/></div>' },
  'a-select': { props: ['value'], template: '<select/>' },
  'a-select-option': { template: '<option/>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-switch': { props: ['checked'], template: '<button class="fake-switch"/>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="tab-pane"><slot/></div>' },
  'a-table': { props: ['dataSource'], template: '<div class="table">{{ dataSource }}</div>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tag': { template: '<span class="page-tag"><slot/></span>' },
  'a-tooltip': { template: '<div><slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(AgentFirewallPage, { global: { plugins: [i18n], stubs } })
}

describe('AgentFirewallPage — 3.6-5 装饰态收口', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('L2 保护路径展示后端真实 blocked_paths，不再渲染前端编造清单', async () => {
    const w = mountPage()
    await flushPromises()
    const text = w.text()
    expect(text).toContain('/etc/passwd')
    expect(text).toContain('/etc/shadow')
    expect(text).toContain('/root')
    // 前端编造的装饰清单（后端 GlobalRuleSet 无此条目）不得再出现
    expect(text).not.toContain('.env')
    expect(text).not.toContain('.ssh')
  })

  it('L1 隔离区不再渲染假开关（只翻本地无后端效果）', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('.fake-switch').length).toBe(0)
    expect(w.text()).toContain('内置')
  })

  it('L0 网关校验/净化不再显示「已启用/已禁用」假状态，改内置标注', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.text()).not.toContain('已启用')
    expect(w.text()).not.toContain('已禁用')
  })
})

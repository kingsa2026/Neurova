import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import HealthPage from '@/pages/HealthPage.vue'

// Mock the unified health API module — all UI calls must go through this library
vi.mock('@/api/modules/health', () => ({
  getHealthChecks: vi.fn(),
  getHealthReport: vi.fn(),
  recoverSubsystem: vi.fn(),
  getHealthStatus: vi.fn(),
  getSystemMetrics: vi.fn(),
}))

// Mock ant-design-vue message to avoid DOM side effects
vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import { getHealthChecks, recoverSubsystem } from '@/api/modules/health'

const i18n = createI18n({
  legacy: false,
  locale: 'en-US',
  fallbackLocale: 'en-US',
  messages: { 'en-US': { system: { health: 'Health' }, common: { refresh: 'Refresh', error: 'Error', success: 'Success', noData: 'No data' }, health: { report: 'Report', reportTitle: 'Report' } } },
  globalInjection: true,
})

// Minimal stubs for Glass components — they render slots by default
const globalStubs = {
  GlassPanel: { template: '<div><slot/></div>' },
  GlassCard: { template: '<div><slot name="header"/><slot/><slot name="footer"/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button @click="$emit(\'click\')"><slot/></button>',
  },
}

function mountHealthPage() {
  return mount(HealthPage, {
    global: {
      plugins: [i18n],
      stubs: globalStubs,
    },
  })
}

describe('HealthPage — FE-001: recover uses unified API library', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: mount-time fetch returns empty list
    vi.mocked(getHealthChecks).mockResolvedValue({ data: [] } as any)
    vi.mocked(recoverSubsystem).mockResolvedValue({ data: { recovered: true, message: 'ok' } } as any)
  })

  it('calls healthApi.recoverSubsystem when recover button clicked', async () => {
    // Seed an unhealthy check so the Recover button is rendered
    vi.mocked(getHealthChecks).mockResolvedValue({
      data: [{ name: 'db', status: 'fail', message: 'down', last_check: '', response_time: 0 }],
    } as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    // Find the Recover button (only shown for non-healthy checks)
    const buttons = wrapper.findAll('button')
    const recoverBtn = buttons.find((b) => b.text().includes('Recover'))
    expect(recoverBtn, 'Recover button should be rendered for failing check').toBeTruthy()

    await recoverBtn!.trigger('click')
    await flushPromises()

    // The recover handler must route through the unified API library,
    // not call an undefined `request` global.
    expect(recoverSubsystem).toHaveBeenCalledWith('db')
  })
})

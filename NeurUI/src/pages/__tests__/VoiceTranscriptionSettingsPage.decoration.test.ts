/**
 * 3.6-6 审计收口（R5）：远程 Whisper 表单无保存链路（remoteForm 收集即丢）+
 * 降级链文案写死（后端 chain 数据到手不渲染）。
 * - 后端 RemoteWhisperEngine 配置走环境变量（NEUROVA_ASR_REMOTE_*），无 HTTP
 *   配置端点——装饰表单退役，改就绪状态展示（status.available.remote_whisper
 *   真实读数，asr/manager.py get_consent_status）+ env 配置说明。
 * - 降级链改数据驱动：渲染 whisperStatus.chain（FALLBACK_CHAIN 真实值）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock } = vi.hoisted(() => {
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
  }
  return { apiMock }
})

vi.mock('@/api', () => ({ default: apiMock, api: apiMock, request: apiMock }))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import VoiceTranscriptionSettingsPage from '../VoiceTranscriptionSettingsPage.vue'
import zhCN from '@/i18n/locales/zh-CN'
import { useAuthStore } from '@/stores/auth'

function statusPayload(overrides: Record<string, unknown> = {}) {
  return {
    code: 0,
    data: {
      consent: false,
      model_ready: false,
      model_dir: '',
      active_engine: null,
      available: { funasr: true, remote_whisper: false, whisper: false },
      chain: ['funasr', 'remote_whisper'],
      ...overrides,
    },
  }
}

const passthrough = { template: '<div class="ant-stub"><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-tag', 'a-alert', 'a-button', 'a-input', 'a-input-password'].map((name) => [name, passthrough]),
)

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(VoiceTranscriptionSettingsPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassCard: { props: ['title'], template: '<div class="gc"><div class="gc-title">{{ title }}</div><slot /></div>' },
        GlassButton: { props: ['variant', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
        ...antStubs,
      },
    },
  })
}

describe('VoiceTranscriptionSettingsPage — 3.6-6 装饰表单退役与链路数据驱动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    useAuthStore().user = { user_id: 'a1', username: 'a', role: 'admin' } as any
    apiMock.get.mockResolvedValue(statusPayload())
  })

  it('降级链渲染后端 chain 数据（mock 链缺本地段，写死文案不会命中）', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('funasr → remote_whisper')
    expect(w.text()).not.toContain('funasr → remote_whisper → whisper')
  })

  it('远程卡不再渲染收集即丢的配置表单（baseUrl/apiKey/model 输入框退役）', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.find('input').exists()).toBe(false)
    expect(w.text()).toContain('NEUROVA_ASR_REMOTE_BASE_URL')
  })

  it('远程卡就绪状态读 status.available.remote_whisper 真实读数', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('未配置或不可用')
    apiMock.get.mockResolvedValue(statusPayload({ available: { funasr: true, remote_whisper: true, whisper: false } }))
    const w2 = mountPage()
    await flushPromises()
    expect(w2.text()).toContain('已就绪')
  })
})

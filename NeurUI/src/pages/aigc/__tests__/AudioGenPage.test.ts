/**
 * AudioGenPage 契约（迁移自 AIGCPage.imageContract 音频用例）：
 * JSON 契约取 data.url；code=-1 诚实失败不得误报成功。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))
const generateAudioMock = vi.fn()
const listVoicesMock = vi.fn().mockResolvedValue({ code: 0, data: { voices: [] } })
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(),
  generateImage: vi.fn(),
  generateAudio: (p: any) => generateAudioMock(p),
  submitVideo: vi.fn(),
  listGenerationVoices: () => listVoicesMock(),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
const messageError = vi.fn()
const messageSuccess = vi.fn()
vi.mock('ant-design-vue', () => ({
  message: { success: (...a: any[]) => messageSuccess(...a), error: (...a: any[]) => messageError(...a), info: vi.fn() },
}))

import AudioGenPage from '@/pages/aigc/AudioGenPage.vue'
import { makeAigcI18n, AIGC_STUBS } from './testUtils'

const mountPage = () =>
  mount(AudioGenPage, { global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS } })

describe('AudioGenPage', () => {
  beforeEach(() => {
    generateAudioMock.mockReset()
    listVoicesMock.mockResolvedValue({ code: 0, data: { voices: [] } })
    messageError.mockClear()
    messageSuccess.mockClear()
  })

  it('成功取 JSON data.url 且产物 URL 带凭证', async () => {
    generateAudioMock.mockResolvedValue({ code: 0, data: { url: '/api/v1/generation/files/t_0.wav', path: '/tmp/t.wav' } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.text = '你好'
    await vm.synthesize()
    await flushPromises()
    expect(vm.audioUrl).toBe('/api/v1/generation/files/t_0.wav')
    expect(messageSuccess).toHaveBeenCalled()
    expect(wrapper.html()).toContain('access_token=tok')
  })

  it('code=-1 显示真实错误且不报成功', async () => {
    generateAudioMock.mockResolvedValue({ code: -1, message: 'TTS 引擎未就绪' })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.text = '你好'
    await vm.synthesize()
    await flushPromises()
    expect(vm.audioUrl).toBe('')
    expect(messageError).toHaveBeenCalledWith('TTS 引擎未就绪')
    expect(messageSuccess).not.toHaveBeenCalled()
  })

  it('R2：音色下拉用引擎真实枚举，不再硬编码假列表', async () => {
    listVoicesMock.mockResolvedValue({
      code: 0,
      data: { voices: [
        { id: 'en-US-AriaNeural', label: 'Aria（Female en-US）', gender: 'Female', locale: 'en-US' },
        { id: 'zh-CN-XiaoxiaoNeural', label: '晓晓（Female zh-CN）', gender: 'Female', locale: 'zh-CN' },
      ] },
    })
    const wrapper = mountPage()
    await flushPromises()
    const values = wrapper.find('.voice-select').findAll('option').map((o) => o.attributes('value'))
    // 中文音色排前
    expect(values[0]).toBe('zh-CN-XiaoxiaoNeural')
    expect(values).not.toContain('alloy')
  })
})

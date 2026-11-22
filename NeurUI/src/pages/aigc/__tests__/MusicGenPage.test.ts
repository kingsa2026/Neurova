/**
 * MusicGenPage 契约（M1/L5 多模态追平）：
 * music_generation 能力下拉（无预置音乐模型时诚实提示，不造假下拉）、
 * 提交 POST /generation/music 返回 task_id 后轮询四态、
 * 成功展示音频播放器/下载（产物 URL 带凭证，与音频页同形态）、
 * 失败诚实报错、卸载清理轮询定时器（BUG-24 同款纪律）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([]),
}))
vi.mock('@/api/modules/providers', () => ({
  listProviders: vi.fn().mockResolvedValue([]),
}))
const submitMusicMock = vi.fn()
const musicStatusMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  submitMusic: (p: any) => submitMusicMock(p),
  getMusicTaskStatus: (id: string) => musicStatusMock(id),
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

import MusicGenPage from '@/pages/aigc/MusicGenPage.vue'
import { listModels } from '@/api/modules/models'
import { makeAigcI18n, AIGC_STUBS, optionValues } from './testUtils'

const mountPage = () =>
  mount(MusicGenPage, { global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS } })

describe('MusicGenPage', () => {
  beforeEach(() => {
    submitMusicMock.mockReset()
    submitMusicMock.mockResolvedValue({ code: 0, data: { task_id: 'tk1', status: 'submitted', protocol: 'fal' } })
    musicStatusMock.mockReset()
    musicStatusMock.mockResolvedValue({ code: 0, data: { task_id: 'tk1', status: 'running' } })
    ;(listModels as any).mockReset()
    ;(listModels as any).mockResolvedValue([])
    messageError.mockClear()
    messageSuccess.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('模型下拉 = auto + music_generation 能力（不造假模型）', async () => {
    ;(listModels as any).mockResolvedValue([
      { model_id: 'fal-ai/musicgen', name: 'MusicGen', provider: 'fal', capabilities: ['music_generation'] },
      { model_id: 'flux.1-dev', name: 'FLUX', provider: 'p', capabilities: ['image_generation'] },
    ])
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-music')
    expect(values[0]).toBe('auto')
    expect(values).toContain('fal-ai/musicgen')
    expect(values).not.toContain('flux.1-dev')
    wrapper.unmount()
  })

  it('后端无 music 模型卡时诚实提示，仅保留 auto', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(optionValues(wrapper, '.model-select-music')).toEqual(['auto'])
    expect(wrapper.find('.aigc-music-model-hint').text()).toContain('暂无预置音乐模型')
    wrapper.unmount()
  })

  it('auto 不透传模型；提交载荷含 prompt 与 duration', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '轻快的钢琴曲'
    vm.duration = 45
    await vm.generate()
    const payload = submitMusicMock.mock.calls[0][0]
    expect(payload.model).toBeUndefined()
    expect(payload.prompt).toBe('轻快的钢琴曲')
    expect(payload.duration).toBe(45)
    wrapper.unmount()
  })

  it('提交后按 task_id 轮询，succeeded 展示音频播放器与下载（URL 带凭证）', async () => {
    vi.useFakeTimers()
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '电子舞曲'
    await vm.generate()
    expect(vm.status.status).toBe('submitted')
    musicStatusMock.mockResolvedValue({
      code: 0,
      data: { task_id: 'tk1', status: 'succeeded', url: '/api/v1/generation/files/m1.mp3' },
    })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(musicStatusMock).toHaveBeenCalledWith('tk1')
    expect(vm.status.status).toBe('succeeded')
    expect(vm.status.progress).toBe(100)
    expect(messageSuccess).toHaveBeenCalled()
    expect(wrapper.find('.aigc-music-player audio').exists()).toBe(true)
    expect(wrapper.find('.aigc-music-player audio').attributes('src')).toContain('access_token=tok')
    expect(wrapper.find('.aigc-music-player a.aigc-download').exists()).toBe(true)
    wrapper.unmount()
  })

  it('failed 诚实报错不误报成功', async () => {
    vi.useFakeTimers()
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = 'p'
    await vm.generate()
    musicStatusMock.mockResolvedValue({
      code: 0,
      data: { task_id: 'tk1', status: 'failed', error: 'model runtime crashed' },
    })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(vm.status.status).toBe('failed')
    expect(messageError).toHaveBeenCalledWith('model runtime crashed')
    expect(messageSuccess).not.toHaveBeenCalled()
    expect(wrapper.find('.aigc-music-player audio').exists()).toBe(false)
    wrapper.unmount()
  })

  it('卸载清理轮询定时器（BUG-24 同款纪律）', async () => {
    vi.useFakeTimers()
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = 'p'
    await vm.generate()
    musicStatusMock.mockResolvedValue({ code: 0, data: { task_id: 'tk1', status: 'running' } })
    await vi.advanceTimersByTimeAsync(3000)
    wrapper.unmount()
    const callsBefore = musicStatusMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(9000)
    expect(musicStatusMock.mock.calls.length).toBe(callsBefore)
  })
})

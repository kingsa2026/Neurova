/**
 * VideoGenPage 契约（迁移自 AIGCPage.models/batch3 视频用例）：
 * video_generation 能力下拉、auto 不透传、参考图上传进 ref_images、
 * 提交返回 task_id 后轮询、卸载清理定时器（BUG-24）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([
    { model_id: 'wan2.2-t2v', name: 'Wan', provider: 'p', capabilities: ['video_generation'] },
    { model_id: 'sora-2-pro', name: 'Sora 2 Pro', provider: 'openai', capabilities: ['video_generation'] },
    { model_id: 'flux.1-dev', name: 'FLUX', provider: 'p', capabilities: ['image_generation'] },
  ]),
}))
const submitVideoMock = vi.fn()
const generateImageMock = vi.fn()
const resolveGenerationMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(),
  generateImage: (p: any) => generateImageMock(p),
  generateAudio: vi.fn(),
  submitVideo: (p: any) => submitVideoMock(p),
  resolveGeneration: (kind: string, model: string, pid?: string) => resolveGenerationMock(kind, model, pid),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
const uploadFileMock = vi.fn()
vi.mock('@/api/modules/files', () => ({ uploadFile: (fd: any) => uploadFileMock(fd) }))
const requestGetMock = vi.fn()
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: (...a: any[]) => requestGetMock(...a) },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import VideoGenPage from '@/pages/aigc/VideoGenPage.vue'
import { makeAigcI18n, AIGC_STUBS, optionValues } from './testUtils'

const mountPage = () =>
  mount(VideoGenPage, { global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS } })

describe('VideoGenPage', () => {
  beforeEach(() => {
    submitVideoMock.mockReset()
    submitVideoMock.mockResolvedValue({ data: { task_id: 'tk1', status: 'submitted', protocol: 'wan' } })
    generateImageMock.mockReset()
    generateImageMock.mockResolvedValue({ data: { images: [] } })
    uploadFileMock.mockReset()
    uploadFileMock.mockResolvedValue({ data: { file_id: 'f1', filename: 'frame.png', path: 'C:/proj/storage/users/u1/frame.png' } })
    requestGetMock.mockReset()
    requestGetMock.mockResolvedValue({ data: { status: 'running' } })
  })

  it('模型下拉 = auto + video_generation 能力', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-video')
    expect(values[0]).toBe('auto')
    expect(values).toContain('wan2.2-t2v')
    expect(values).not.toContain('flux.1-dev')
  })

  it('auto 不透传；提交后按 task_id 轮询', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '奔跑的柴犬'
    vm.model = 'auto'
    await vm.generate()
    await flushPromises()
    const payload = submitVideoMock.mock.calls[0][0]
    expect(payload.model).toBeUndefined()
    expect(payload.prompt).toBe('奔跑的柴犬')
    expect(payload.task_id).toBeUndefined?.() // 载荷不含 task_id（提交响应才有）
    wrapper.unmount() // 清理轮询定时器（BUG-24 契约）
  })

  it('R2 两段式：先出静帧，静帧本地产物作首帧 ref_images 提交', async () => {
    generateImageMock.mockResolvedValue({
      data: { images: [{ url: '/api/v1/generation/files/f_0.png', path: 'C:/data/generations/f_0.png' }] },
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '猫宇航员'
    vm.staticFirst = true
    await vm.generate()
    await flushPromises()
    expect(generateImageMock).toHaveBeenCalledTimes(1)
    const payload = submitVideoMock.mock.calls[0][0]
    expect(payload.ref_images).toEqual(['C:/data/generations/f_0.png'])
    wrapper.unmount()
  })

  it('R2 两段式关闭时不先生成静帧', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = 'p'
    vm.staticFirst = false
    await vm.generate()
    expect(generateImageMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('参考图上传进 ref_images', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.onRefUpload(new File(['y'], 'frame.png', { type: 'image/png' }))
    await flushPromises()
    expect(vm.refImages).toEqual(['C:/proj/storage/users/u1/frame.png'])
    vm.prompt = 'p'
    await vm.generate()
    expect(submitVideoMock.mock.calls[0][0].ref_images).toEqual(['C:/proj/storage/users/u1/frame.png'])
    wrapper.unmount()
  })

  // ── 2026-09-15 模型自适应（协议/服务商不再手填）───────────────────────
  it('无手填「生成协议/服务商 ID」输入（改自适应推导）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.protocol).toBeUndefined()
    expect(vm.providerId).toBeUndefined()
    wrapper.unmount()
  })

  it('选具体模型 → 调 /generation/resolve 自适应展示协议与服务商', async () => {
    resolveGenerationMock.mockReset()
    resolveGenerationMock.mockResolvedValue({ data: { protocol: 'sora', provider_id: 'openai' } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.model = 'sora-2-pro'
    await flushPromises()
    expect(resolveGenerationMock).toHaveBeenCalledWith('video', 'sora-2-pro', 'openai')
    expect(wrapper.find('.aigc-derived-hint').text()).toContain('sora')
    wrapper.unmount()
  })

  it('auto 态不查推导，提示自动识别', async () => {
    resolveGenerationMock.mockReset()
    const wrapper = mountPage()
    await flushPromises()
    expect(resolveGenerationMock).not.toHaveBeenCalled()
    expect(wrapper.find('.aigc-derived-hint').text()).toContain('自动识别')
    wrapper.unmount()
  })

  it('提交载荷=model+provider_id 反查，不传 protocol（服务端推导）', async () => {
    resolveGenerationMock.mockResolvedValue({ data: { protocol: 'sora', provider_id: 'openai' } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = 'p'
    vm.model = 'sora-2-pro'
    vm.staticFirst = false
    await vm.generate()
    const payload = submitVideoMock.mock.calls[0][0]
    expect(payload.model).toBe('sora-2-pro')
    expect(payload.provider_id).toBe('openai')
    expect('protocol' in payload).toBe(false)
    wrapper.unmount()
  })
})

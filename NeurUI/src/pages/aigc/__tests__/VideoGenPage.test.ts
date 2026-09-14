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
    { model_id: 'flux.1-dev', name: 'FLUX', provider: 'p', capabilities: ['image_generation'] },
  ]),
}))
const submitVideoMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(),
  generateImage: vi.fn(),
  generateAudio: vi.fn(),
  submitVideo: (p: any) => submitVideoMock(p),
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
})

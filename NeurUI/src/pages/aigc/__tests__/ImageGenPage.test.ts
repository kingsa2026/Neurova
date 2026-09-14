/**
 * ImageGenPage 契约（迁移自 AIGCPage.models/imageContract/batch3 测试）：
 * 能力过滤下拉、auto 不透传、风格注入、参考图上传闭环、产物 token 化 URL、
 * 记录侧栏挂载。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([
    { model_id: 'deepseek-chat', name: 'DS', provider: 'p', capabilities: ['text'] },
    { model_id: 'flux.1-dev', name: 'FLUX', provider: 'prov-b', capabilities: ['image_generation'] },
  ]),
}))
const generateImageMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(),
  generateImage: (p: any) => generateImageMock(p),
  generateAudio: vi.fn(),
  submitVideo: vi.fn(),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
const uploadFileMock = vi.fn()
vi.mock('@/api/modules/files', () => ({ uploadFile: (fd: any) => uploadFileMock(fd) }))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import ImageGenPage from '@/pages/aigc/ImageGenPage.vue'
import { makeAigcI18n, AIGC_STUBS, optionValues } from './testUtils'

const mountPage = () =>
  mount(ImageGenPage, { global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS } })

describe('ImageGenPage', () => {
  beforeEach(() => {
    generateImageMock.mockReset()
    generateImageMock.mockResolvedValue({ data: { images: [{ url: '/api/v1/generation/files/a_0.png', path: 'a' }] } })
    uploadFileMock.mockReset()
    uploadFileMock.mockResolvedValue({ data: { file_id: 'f1', filename: 'ref.png', path: 'C:/proj/storage/users/u1/ref.png' } })
  })

  it('模型下拉 = auto + image_generation 能力模型', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-image')
    expect(values[0]).toBe('auto')
    expect(values).toContain('flux.1-dev')
    expect(values).not.toContain('deepseek-chat')
  })

  it('auto 不透传 + default 模板无注入 + 结果 URL 带访问凭证', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '一只柴犬'
    vm.model = 'auto'
    vm.template = 'default'
    await vm.generate()
    await flushPromises()
    const payload = generateImageMock.mock.calls[0][0]
    expect(payload.model).toBeUndefined()
    expect(payload.prompt).toBe('一只柴犬')
    expect('style' in payload).toBe(false)
    expect(wrapper.html()).toContain('access_token=tok')
  })

  it('anime 模板注入风格提示词', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.prompt = '一只柴犬'
    vm.template = 'anime'
    await vm.generate()
    expect(generateImageMock.mock.calls[0][0].prompt).toContain('anime style')
  })

  it('参考图上传后随生成请求提交 ref_images', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.onRefUpload(new File(['x'], 'cat.png', { type: 'image/png' }))
    await flushPromises()
    expect(uploadFileMock).toHaveBeenCalled()
    expect(vm.refImages).toEqual(['C:/proj/storage/users/u1/ref.png'])
    vm.prompt = '变体'
    await vm.generate()
    expect(generateImageMock.mock.calls[0][0].ref_images).toEqual(['C:/proj/storage/users/u1/ref.png'])
  })

  it('挂载记录侧栏（默认过滤 image）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findComponent({ name: 'AigcHistoryList' }).exists()
      || wrapper.html().includes('aigc-history')).toBe(true)
  })
})

/**
 * TextGenPage 契约（迁移自 AIGCPage.models 文本用例）：
 * text 能力下拉（含推理模型、不含纯生成模型）、auto 首选默认、结果透传。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// 注意：本页面用 renderMarkdown（依赖真实 @/utils/security 的 sanitizeHtmlStrict），
// 不 mock security 模块，jsdom 环境下 DOMPurify 正常工作。
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([
    { model_id: 'deepseek-chat', name: 'DS Chat', provider: 'prov-a', capabilities: ['text'] },
    { model_id: 'deepseek-r1', name: 'DS R1', provider: 'prov-a', capabilities: ['text', 'reasoning'] },
    { model_id: 'qwen-vl-max', name: 'Qwen VL', provider: 'prov-a', capabilities: ['text', 'vision'] },
    { model_id: 'flux.1-dev', name: 'FLUX', provider: 'prov-b', capabilities: ['image_generation'] },
    { model_id: 'wan2.2-t2v', name: 'Wan', provider: 'prov-b', capabilities: ['video_generation'] },
  ]),
}))
const generateTextMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: (p: any) => generateTextMock(p),
  generateImage: vi.fn(),
  generateAudio: vi.fn(),
  submitVideo: vi.fn(),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import TextGenPage from '@/pages/aigc/TextGenPage.vue'
import { makeAigcI18n, AIGC_STUBS, optionValues } from './testUtils'

const mountPage = () =>
  mount(TextGenPage, { global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS } })

describe('TextGenPage', () => {
  beforeEach(() => generateTextMock.mockReset())

  it('text 能力下拉：auto + 含推理/视觉文本模型，不含纯生成模型', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-text')
    expect(values[0]).toBe('auto')
    expect(values).toContain('deepseek-chat')
    expect(values).toContain('deepseek-r1')
    expect(values).toContain('qwen-vl-max')
    expect(values).not.toContain('flux.1-dev')
    expect(values).not.toContain('wan2.2-t2v')
  })

  it('默认选中 auto 并透传给后端路由', async () => {
    generateTextMock.mockResolvedValue({ data: { text: 'echo', routed: true } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.model).toBe('auto')
    vm.prompt = '你好'
    await vm.generate()
    await flushPromises()
    expect(generateTextMock).toHaveBeenCalledWith({ prompt: '你好', model: 'auto' })
  })
})

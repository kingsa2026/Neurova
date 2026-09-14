/**
 * StudioPage 契约（迁移自 AIGCPage.studio.test.ts）：
 * 一键成片以固定模板 id 与表单入参跑工作流；产物合并为连播数据。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(), generateImage: vi.fn(), generateAudio: vi.fn(), submitVideo: vi.fn(),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return { ...actual, useRouter: () => ({ push: vi.fn() }) }
})
const messageSuccess = vi.fn()
vi.mock('ant-design-vue', () => ({
  message: { success: (...a: any[]) => messageSuccess(...a), error: vi.fn(), info: vi.fn() },
}))

let studioOutputs: Record<string, unknown> | null = null
const runTemplateMock = vi.fn()
vi.mock('@/composables/useWorkflowRun', () => ({
  useWorkflowRun: () => ({
    running: { value: false },
    steps: { value: [{ id: 'script', label: '剧本生成', status: 'success' }] },
    lastError: { value: '' },
    outputs: { value: studioOutputs },
    workflowId: { value: 'wf_test_1' },
    runTemplate: (...a: any[]) => runTemplateMock(...a),
    cleanup: vi.fn(),
  }),
}))

import StudioPage from '@/pages/aigc/StudioPage.vue'
import { makeAigcI18n, AIGC_STUBS } from './testUtils'

const mountPage = () =>
  mount(StudioPage, { global: { plugins: [makeAigcI18n()], stubs: { ...AIGC_STUBS } } })

describe('StudioPage', () => {
  beforeEach(() => {
    runTemplateMock.mockReset()
    messageSuccess.mockClear()
    studioOutputs = null
  })

  it('一键成片：固定模板 id + 表单入参跑工作流', async () => {
    runTemplateMock.mockResolvedValue({ ok: true, executionId: 'ex', status: 'completed', outputs: null, error: '' })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.theme = '落魄赘婿龙王归来'
    vm.style = '国风水墨'
    await vm.run()
    expect(runTemplateMock).toHaveBeenCalledTimes(1)
    const [templateId, name, inputs] = runTemplateMock.mock.calls[0]
    expect(templateId).toBe('template_short_drama')
    expect(name).toContain('落魄赘婿')
    expect(inputs.theme).toBe('落魄赘婿龙王归来')
    expect(inputs.style).toBe('国风水墨')
    expect(messageSuccess).toHaveBeenCalled()
  })

  it('完成后连播数据合并（images+storyboard+audio）', async () => {
    studioOutputs = {
      storyboard: [{ description: '镜一', narration: '旁白一' }],
      images: [{ shot: 1, url: '/api/v1/generation/files/a_0.png', prompt: 'p' }],
      audio: [{ url: '/api/v1/generation/files/v_0.wav' }],
      compose: { composed: false, mode: 'slideshow_manifest' },
    }
    runTemplateMock.mockResolvedValue({ ok: true, executionId: 'ex', status: 'completed', outputs: studioOutputs, error: '' })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.theme = 't'
    await vm.run()
    await flushPromises()
    expect(vm.studioItems.length).toBe(1)
    expect(vm.studioItems[0].audio).toContain('v_0.wav')
    expect(vm.studioItems[0].description).toBe('镜一')
  })
})

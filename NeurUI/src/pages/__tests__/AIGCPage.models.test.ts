/**
 * AIGCPage — 模型下拉按能力过滤 + auto 自动路由选项（2026-09-03）
 *
 * 用户需求：
 * 1. 模型管理自动检测六类能力（text/reasoning/vision/video/image_generation/
 *    video_generation）并持久化；
 * 2. AIGC 各 Tab 的模型下拉自动列出对应能力的模型，或选 "auto"
 *    （LLMRouter 自动路由）。
 *
 * 契约（防回归）：
 * - 数据源 = GET /models（listModels），按 capabilities 过滤；
 *   文本 Tab → text；图像 Tab → image_generation；视频 Tab → video_generation；
 * - 每个下拉首选项恒为 auto（LLM 自动路由），默认选中；
 * - 生成请求把所选 model 透传给后端（auto → 'auto'）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn(),
}))

vi.mock('@/api/modules/image', () => ({
  getTemplates: vi.fn().mockResolvedValue({ data: { templates: [] } }),
}))

vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn().mockResolvedValue({ data: { text: 'ok' } }),
  generateImage: vi.fn().mockResolvedValue({ data: { urls: ['http://x/1.png'] } }),
}))

vi.mock('@/api', () => ({
  request: { post: vi.fn().mockResolvedValue({ data: {} }), get: vi.fn().mockResolvedValue({ data: {} }) },
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { listModels } from '@/api/modules/models'
import AIGCPage from '@/pages/AIGCPage.vue'

const listMock = listModels as unknown as ReturnType<typeof vi.fn>

const MODELS = [
  { model_id: 'deepseek-chat', name: 'DeepSeek Chat', provider: 'prov-a', capabilities: ['text'] },
  { model_id: 'deepseek-r1', name: 'DeepSeek R1', provider: 'prov-a', capabilities: ['text', 'reasoning'] },
  { model_id: 'qwen-vl-max', name: 'Qwen VL Max', provider: 'prov-a', capabilities: ['text', 'vision'] },
  { model_id: 'flux.1-dev', name: 'FLUX.1 Dev', provider: 'prov-b', capabilities: ['image_generation'] },
  { model_id: 'wan2.2-t2v', name: 'Wan2.2 T2V', provider: 'prov-b', capabilities: ['video_generation'] },
]

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ui: { autoRoute: 'Auto（LLM 自动路由）' },
      aigc: {
        title: 'AIGC', text: '文本', image: '图像', audio: '音频', video: '视频',
        prompt: '提示词', model: '模型', textPromptPlaceholder: '', selectModel: '选择模型',
        generate: '生成', result: '结果', noResult: '', imagePromptPlaceholder: '',
        template: '模板', selectTemplate: '', gallery: '画廊', noImages: '',
        textInput: '文本', audioPromptPlaceholder: '', selectVoice: '', synthesize: '合成',
        audioResult: '音频', noAudio: '', videoPromptPlaceholder: '', videoStatus: '状态',
        status: '状态', progress: '进度', videoUrl: '链接', noVideo: '',
      },
    },
  },
})

const mountPage = () =>
  mount(AIGCPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { template: '<div><slot /></div>' },
        GlassCard: { props: ['title'], template: '<div><slot /></div>' },
        GlassButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'a-tabs': { template: '<div><slot /></div>' },
        'a-tab-pane': { template: '<div><slot /></div>' },
        'a-form': { template: '<div><slot /></div>' },
        'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
        'a-textarea': { template: '<textarea />' },
        'a-select': {
          props: ['options'],
          template:
            '<select class="stub-select"><option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option></select>',
        },
        'a-empty': { template: '<div />' },
        'a-modal': { template: '<div><slot /></div>' },
        'a-descriptions': { template: '<div><slot /></div>' },
        'a-descriptions-item': { template: '<div><slot /></div>' },
        'a-progress': { template: '<div />' },
      },
    },
  })

/** 按选择器取下拉的 option 值列表。 */
function optionValues(wrapper: ReturnType<typeof mountPage>, selector: string): string[] {
  const sel = wrapper.find(selector)
  expect(sel.exists(), `应存在 ${selector}`).toBe(true)
  return sel.findAll('option').map((o) => o.attributes('value') ?? '')
}

describe('AIGCPage 能力过滤下拉', () => {
  beforeEach(() => {
    listMock.mockReset()
    listMock.mockResolvedValue(MODELS)
  })

  it('文本 Tab 下拉 = auto + text 能力模型（含推理模型，不含纯生成模型）', async () => {
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

  it('图像 Tab 下拉 = auto + image_generation 模型', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-image')
    expect(values[0]).toBe('auto')
    expect(values).toContain('flux.1-dev')
    expect(values).not.toContain('deepseek-chat')
    expect(values).not.toContain('wan2.2-t2v')
  })

  it('视频 Tab 下拉 = auto + video_generation 模型', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const values = optionValues(wrapper, '.model-select-video')
    expect(values[0]).toBe('auto')
    expect(values).toContain('wan2.2-t2v')
    expect(values).not.toContain('flux.1-dev')
    expect(values).not.toContain('deepseek-chat')
  })

  it('默认选中 auto（LLMRouter 自动路由）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect((wrapper.vm as any).textModel).toBe('auto')
    expect((wrapper.vm as any).imageModel).toBe('auto')
    expect((wrapper.vm as any).videoModel).toBe('auto')
  })

  it('能力数据缺失（接口失败）时下拉仍保底 auto 选项', async () => {
    listMock.mockRejectedValue(new Error('network'))
    const wrapper = mountPage()
    await flushPromises()
    expect(optionValues(wrapper, '.model-select-text')).toEqual(['auto'])
    expect(optionValues(wrapper, '.model-select-image')).toEqual(['auto'])
  })
})

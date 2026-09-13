/**
 * AIGCPage 批次1 图像/音频契约回归：
 * 1. 图像「模板」不再错接 Docker 构建模板接口（GET /v1/image/templates），
 *    改为内置风格模板并把风格提示词注入 prompt（后端 ImageGenerationRequest
 *    无 style 字段，旧实现静默丢弃）；
 * 2. 图像 model=auto 不再把 "auto" 当真实模型名发给后端（后端现按能力路由，
 *    前端 undefined 与之对齐，同视频 Tab 既有做法）；
 * 3. 音频统一 JSON 契约：成功取 data.url；后端诚实失败（code=-1）时不得
 *    再误报成功 toast。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([]),
}))

const getTemplatesMock = vi.fn().mockResolvedValue({ data: { templates: [] } })
vi.mock('@/api/modules/image', () => ({
  getTemplates: () => getTemplatesMock(),
}))

const generateImageMock = vi.fn().mockResolvedValue({ data: { images: [{ url: '/api/v1/generation/files/a_0.png', path: 'a_0.png' }] } })
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn().mockResolvedValue({ data: { text: 'ok' } }),
  generateImage: (p: any) => generateImageMock(p),
}))

const requestPostMock = vi.fn()
vi.mock('@/api', () => ({
  default: { post: (...a: any[]) => requestPostMock(...a), get: vi.fn() },
  request: { post: (...a: any[]) => requestPostMock(...a), get: vi.fn().mockResolvedValue({ data: {} }) },
}))

const messageErrorMock = vi.fn()
const messageSuccessMock = vi.fn()
vi.mock('ant-design-vue', () => ({
  message: { success: (...a: any[]) => messageSuccessMock(...a), error: (...a: any[]) => messageErrorMock(...a), info: vi.fn() },
}))

import AIGCPage from '@/pages/AIGCPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ui: { autoRoute: 'Auto', yes: '是', no: '否' },
      aigc: {
        title: 'AIGC', text: '文本', image: '图像', audio: '音频', video: '视频',
        prompt: '提示词', model: '模型', textPromptPlaceholder: '', imagePromptPlaceholder: '',
        audioPromptPlaceholder: '', videoPromptPlaceholder: '', selectModel: '', selectVoice: '',
        generate: '生成', result: '结果', noResult: '', template: '模板', selectTemplate: '',
        gallery: '画廊', noImages: '', textInput: '文本', synthesize: '合成', audioResult: '音频',
        noAudio: '', videoStatus: '状态', status: '状态', progress: '进度', videoUrl: '链接',
        noVideo: '', generateError: '生成失败', imageSuccess: '成功', audioSuccess: '音频成功',
        videoSuccess: '', videoFailed: '', default: '默认', photorealistic: '照片级',
        anime: '动漫', oilPainting: '油画', protocol: '协议', protocolAuto: '',
        providerId: '服务商', providerIdHint: '', duration: '时长', resolution: '分辨率',
        refImage: '参考图', refImageHint: '', voiceAlloy: '', voiceEcho: '',
        voiceFable: '', voiceOnyx: '', voiceNova: '', voiceShimmer: '',
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
        'a-input': { props: ['value'], template: '<input />' },
        'a-input-number': { template: '<input />' },
        'a-select': { props: ['options'], template: '<select><option v-for="o in options || []" :value="o.value">{{ o.label }}</option></select>' },
        'a-select-option': { props: ['value'], template: '<option><slot /></option>' },
        'a-empty': { template: '<div />' },
        'a-modal': { template: '<div><slot /></div>' },
        'a-descriptions': { template: '<div><slot /></div>' },
        'a-descriptions-item': { template: '<div><slot /></div>' },
        'a-progress': { template: '<div />' },
      },
    },
  })

describe('AIGCPage 批次1 图像/音频契约', () => {
  beforeEach(() => {
    getTemplatesMock.mockClear()
    generateImageMock.mockClear()
    requestPostMock.mockReset()
    messageErrorMock.mockClear()
    messageSuccessMock.mockClear()
  })

  it('不再拉取 Docker 构建模板接口当图像风格模板', async () => {
    mountPage()
    await flushPromises()
    expect(getTemplatesMock).not.toHaveBeenCalled()
  })

  it('auto 不作为模型名透传；风格模板注入 prompt', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.imagePrompt = '一只柴犬'
    vm.imageTemplate = 'anime'
    vm.imageModel = 'auto'
    await vm.generateImage()
    await flushPromises()

    expect(generateImageMock).toHaveBeenCalledTimes(1)
    const payload = generateImageMock.mock.calls[0][0]
    expect(payload.model).toBeUndefined()
    expect(payload.prompt).toContain('一只柴犬')
    // 风格提示词注入（旧实现发 style 字段但后端无此字段 → 静默丢弃）
    expect(payload.prompt).not.toBe('一只柴犬')
    expect('style' in payload).toBe(false)
  })

  it('显式模型仍透传', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.imagePrompt = 'p'
    vm.imageTemplate = 'default'
    vm.imageModel = 'flux.1-dev'
    await vm.generateImage()
    await flushPromises()
    const payload = generateImageMock.mock.calls[0][0]
    expect(payload.model).toBe('flux.1-dev')
    // default 模板不注入风格后缀
    expect(payload.prompt).toBe('p')
  })

  it('音频成功走 JSON url；后端 code=-1 不得误报成功', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any

    requestPostMock.mockResolvedValueOnce({ code: 0, data: { url: '/api/v1/generation/files/t_0.wav', path: '/tmp/t_0.wav' } })
    vm.audioText = '你好'
    await vm.generateAudio()
    await flushPromises()
    expect(vm.audioUrl).toBe('/api/v1/generation/files/t_0.wav')
    expect(messageSuccessMock).toHaveBeenCalled()

    requestPostMock.mockResolvedValueOnce({ code: -1, message: 'TTS 引擎未就绪' })
    vm.audioText = '再来'
    await vm.generateAudio()
    await flushPromises()
    expect(vm.audioUrl).toBe('')
    expect(messageErrorMock).toHaveBeenCalled()
    expect(messageSuccessMock).toHaveBeenCalledTimes(1) // 第二次的失败不得触发成功 toast
  })
})

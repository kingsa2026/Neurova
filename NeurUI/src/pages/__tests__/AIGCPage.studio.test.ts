/**
 * AIGC 创作 Tab（批次4）：一句话主题 → 跑内置短剧模板工作流 → 连播成片。
 * 打通契约：创作 Tab 是画布工作流的消费者（useWorkflowRun 内核），
 * 产物（images/audio/compose）与「记录」「画布运行历史」同池。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(), generateImage: vi.fn(),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))
vi.mock('@/api/modules/files', () => ({ uploadFile: vi.fn() }))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

let studioOutputsFixture: Record<string, unknown> | null = null
const runTemplateMock = vi.fn()
vi.mock('@/composables/useWorkflowRun', () => ({
  useWorkflowRun: () => ({
    running: { value: false },
    steps: { value: [{ id: 'script', label: '剧本生成', status: 'success' }] },
    lastError: { value: '' },
    outputs: { value: studioOutputsFixture },
    workflowId: { value: 'wf_test_1' },
    runTemplate: (...a: any[]) => runTemplateMock(...a),
    cleanup: vi.fn(),
  }),
}))

import AIGCPage from '@/pages/AIGCPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en-US',
  messages: {
    'zh-CN': {
      common: { refresh: '刷新', upload: '上传', yes: '是', no: '否' },
      ui: { autoRoute: 'Auto' },
      aigc: {
        title: 'AIGC', text: '文本', image: '图像', audio: '音频', video: '视频', history: '记录',
        studio: '创作', prompt: '提示词', model: '模型', result: '结果', noResult: '暂无',
        generate: '生成', download: '下载', all: '全部',
        studioTheme: '主题', studioGenerate: '一键成片', studioRunning: '生成中',
        studioOpenWorkflow: '在工作流中打开', studioOk: '成片完成', studioEmpty: '等待创作',
        template: '模板', selectTemplate: '', gallery: '画廊', noImages: '', textInput: '文本',
        audioResult: '音频', noAudio: '', videoStatus: '状态', status: '状态', progress: '进度',
        videoUrl: '链接', noVideo: '', generateError: '失败', imageSuccess: '成',
        audioSuccess: '成', videoSuccess: '', videoFailed: '', default: '默认',
        photorealistic: '照片', anime: '动漫', oilPainting: '油画', protocol: '协议',
        protocolAuto: '', providerId: '服务商', providerIdHint: '', duration: '时长',
        resolution: '分辨率', refImage: '参考图', refImageHint: '', selectModel: '',
        selectVoice: '', textPromptPlaceholder: '', imagePromptPlaceholder: '',
        audioPromptPlaceholder: '', videoPromptPlaceholder: '', synthesize: '合成',
        voiceAlloy: '', voiceEcho: '', voiceFable: '', voiceOnyx: '', voiceNova: '',
        voiceShimmer: '', noHistory: '无', stSubmitted: '排队', stRunning: '生成中',
        stSucceeded: '成', stFailed: '败', studioShot: '镜头', studioPlay: '播放',
        studioPause: '暂停', studioPrev: '上', studioNext: '下',
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
        'a-empty': { template: '<div><slot /></div>' },
        'a-modal': { template: '<div><slot /></div>' },
        'a-descriptions': { template: '<div><slot /></div>' },
        'a-descriptions-item': { template: '<div><slot /></div>' },
        'a-progress': { template: '<div />' },
        'a-radio-group': { template: '<div><slot /></div>' },
        'a-radio-button': { props: ['value'], template: '<span><slot /></span>' },
        'a-tag': { template: '<span><slot /></span>' },
        'a-tooltip': { template: '<span><slot /></span>' },
        'a-upload': { props: ['customRequest'], template: '<span><slot /></span>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-steps': { template: '<div><slot /></div>' },
        'a-step': { props: ['title', 'status'], template: '<div>{{ title }}</div>' },
      },
    },
  })

describe('AIGC 创作 Tab', () => {
  beforeEach(() => {
    runTemplateMock.mockReset()
    studioOutputsFixture = null
  })

  it('一键成片：以固定模板 id 与表单入参跑工作流', async () => {
    runTemplateMock.mockResolvedValue({ ok: true, executionId: 'ex', status: 'completed', outputs: null, error: '' })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'studio'
    vm.studioTheme = '落魄赘婿龙王归来'
    vm.studioStyle = '国风水墨'
    await vm.runStudio()
    await flushPromises()
    expect(runTemplateMock).toHaveBeenCalledTimes(1)
    const [templateId, name, inputs] = runTemplateMock.mock.calls[0]
    expect(templateId).toBe('template_short_drama')
    expect(name).toContain('落魄赘婿')
    expect(inputs.theme).toBe('落魄赘婿龙王归来')
    expect(inputs.style).toBe('国风水墨')
  })

  it('运行完成后渲染连播播放器数据（images+storyboard+audio 合并）', async () => {
    studioOutputsFixture = {
      storyboard: [{ description: '镜一', narration: '旁白一' }],
      images: [{ shot: 1, url: '/api/v1/generation/files/a_0.png', prompt: 'p' }],
      audio: [{ url: '/api/v1/generation/files/v_0.wav' }],
      compose: { composed: false, mode: 'slideshow_manifest' },
    }
    runTemplateMock.mockResolvedValue({ ok: true, executionId: 'ex', status: 'completed', outputs: studioOutputsFixture, error: '' })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'studio'
    vm.studioTheme = 't'
    await vm.runStudio()
    await flushPromises()
    expect(vm.studioItems.length).toBe(1)
    expect(vm.studioItems[0].audio).toContain('v_0.wav')
    expect(vm.studioItems[0].description).toBe('镜一')
  })
})

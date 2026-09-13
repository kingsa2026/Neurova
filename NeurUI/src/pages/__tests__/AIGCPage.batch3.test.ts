/**
 * AIGCPage 批次3：产物 URL 携带访问凭证 + 参考图上传闭环。
 *
 * 根因：产物文件从匿名 StaticFiles 收口为鉴权路由后，<img>/<audio>/<a download>
 * 无法带 Authorization 头 → 前端须统一追加 ?access_token=；参考图上传复用
 * /files/upload（后端允许根已含 storage），形成 上传→ref_images→生成 闭环。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn((k: string) => (k === 'auth_token' ? 'tok-123' : null)), set: vi.fn(), remove: vi.fn() },
}))

vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([]),
}))

const generateImageMock = vi.fn().mockResolvedValue({ data: { images: [] } })
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn().mockResolvedValue({ data: { text: 'ok' } }),
  generateImage: (p: any) => generateImageMock(p),
  listGenerationTasks: vi.fn().mockResolvedValue({ code: 0, data: { tasks: [] } }),
}))

const uploadFileMock = vi.fn()
vi.mock('@/api/modules/files', () => ({
  uploadFile: (fd: any) => uploadFileMock(fd),
}))

vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import AIGCPage from '@/pages/AIGCPage.vue'
import { withFileToken } from '@/utils/genFiles'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { refresh: '刷新', yes: '是', no: '否', upload: '上传' },
      ui: { autoRoute: 'Auto' },
      aigc: {
        title: 'AIGC', text: '文本', image: '图像', audio: '音频', video: '视频',
        prompt: '提示词', model: '模型', textPromptPlaceholder: '', imagePromptPlaceholder: '',
        audioPromptPlaceholder: '', videoPromptPlaceholder: '', selectModel: '', selectVoice: '',
        generate: '生成', result: '结果', noResult: '', template: '模板', selectTemplate: '',
        gallery: '画廊', noImages: '', textInput: '文本', synthesize: '合成', audioResult: '音频',
        noAudio: '', videoStatus: '状态', status: '状态', progress: '进度', videoUrl: '链接',
        noVideo: '', generateError: '生成失败', imageSuccess: '成功', audioSuccess: '成功',
        videoSuccess: '', videoFailed: '', default: '默认', photorealistic: '照',
        anime: '漫', oilPainting: '油', protocol: '协议', protocolAuto: '',
        providerId: '服务商', providerIdHint: '', duration: '时长', resolution: '分辨率',
        refImage: '参考图', refImageHint: '', voiceAlloy: '', voiceEcho: '',
        voiceFable: '', voiceOnyx: '', voiceNova: '', voiceShimmer: '',
        history: '记录', download: '下载', all: '全部', noHistory: '无',
        stSubmitted: '排队', stRunning: '生成中', stSucceeded: '成功', stFailed: '失败',
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
        'a-upload': { props: ['customRequest'], template: '<button class="upload-stub" @click="$props.customRequest && $props.customRequest({ file: { name: \'cat.png\', size: 10 } })"><slot /></button>' },
      },
    },
  })

describe('withFileToken', () => {
  it('本地产物 URL 追加 access_token；外链原样', () => {
    expect(withFileToken('/api/v1/generation/files/a.png')).toBe(
      '/api/v1/generation/files/a.png?access_token=tok-123')
    expect(withFileToken('http://cdn/x.png')).toBe('http://cdn/x.png')
    expect(withFileToken('')).toBe('')
  })
})

describe('AIGCPage 批次3', () => {
  beforeEach(() => {
    generateImageMock.mockClear()
    uploadFileMock.mockReset()
    uploadFileMock.mockResolvedValue({ data: { file_id: 'f1', filename: 'cat.png', path: 'C:/proj/storage/users/u1/agents/default/cat.png' } })
  })

  it('图像画廊展示 URL 带访问凭证', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.imageResults = [{ url: '/api/v1/generation/files/t1_0.png', prompt: 'x' }]
    await vm.$nextTick()
    expect(wrapper.html()).toContain('access_token=tok-123')
  })

  it('参考图上传后随生成请求提交 ref_images', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.onRefUpload(new File(['x'], 'cat.png', { type: 'image/png' }), 'image')
    await flushPromises()
    expect(uploadFileMock).toHaveBeenCalled()
    expect(vm.imageRefImages).toEqual(['C:/proj/storage/users/u1/agents/default/cat.png'])

    vm.imagePrompt = '变体'
    await vm.generateImage()
    const payload = generateImageMock.mock.calls[0][0]
    expect(payload.ref_images).toEqual(['C:/proj/storage/users/u1/agents/default/cat.png'])
  })

  it('视频 Tab 参考图同样走上传（替代手填路径文本框）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.onRefUpload(new File(['y'], 'frame.png', { type: 'image/png' }), 'video')
    await flushPromises()
    expect(vm.videoRefImages).toEqual(['C:/proj/storage/users/u1/agents/default/cat.png'])
  })
})

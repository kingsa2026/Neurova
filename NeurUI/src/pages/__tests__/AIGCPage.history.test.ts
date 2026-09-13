/**
 * AIGCPage 批次2「记录」Tab：GET /generation/tasks 历史面板契约。
 *
 * 根因：后端账本接口早已存在但前端零消费（图像/视频/音频产物生成后离开页面即
 * 无处找回）。本测试锁定：进入记录 Tab 拉取任务、按 kind 过滤、产物预览/下载、
 * 失败原因可见、未决任务自动刷新。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue([]),
}))

const listTasksMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn().mockResolvedValue({ data: { text: 'ok' } }),
  generateImage: vi.fn().mockResolvedValue({ data: { images: [] } }),
  listGenerationTasks: (params: any) => listTasksMock(params),
}))

vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import AIGCPage from '@/pages/AIGCPage.vue'

const TASKS = [
  {
    task_id: 't1', kind: 'image', protocol: 'openai_compat', model: 'flux',
    status: 'succeeded', prompt: '一只柴犬', submitted_at: 1757700000, updated_at: 1757700001,
    local_path: '/data/generations/t1_0.png', url: '/api/v1/generation/files/t1_0.png',
    source: 'rest', error: '',
  },
  {
    task_id: 't2', kind: 'video', protocol: 'wan', model: 'wan3.0-t2v',
    status: 'running', prompt: '奔跑', submitted_at: 1757700100, updated_at: 1757700101,
    local_path: '', url: '', source: 'rest', error: '',
  },
  {
    task_id: 't3', kind: 'audio', protocol: 'tts', model: '',
    status: 'failed', prompt: '你好', submitted_at: 1757700200, updated_at: 1757700201,
    local_path: '', url: '', source: 'channel', error: 'TTS 引擎未就绪',
  },
]

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
        history: '记录', download: '下载', all: '全部', noHistory: '暂无记录',
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
      },
    },
  })

describe('AIGCPage 记录 Tab', () => {
  beforeEach(() => {
    listTasksMock.mockReset()
    listTasksMock.mockResolvedValue({ code: 0, data: { tasks: TASKS } })
  })

  it('进入记录 Tab 拉取任务账本并渲染三类产物', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'history'
    await flushPromises()
    await vm.$nextTick()

    expect(listTasksMock).toHaveBeenCalled()
    expect(vm.historyTasks.length).toBe(3)
    // 图像产物缩略图 + 下载链接
    expect(wrapper.html()).toContain('/api/v1/generation/files/t1_0.png')
    // 失败任务展示错误原因
    expect(wrapper.text()).toContain('TTS 引擎未就绪')
    // 状态文案
    expect(wrapper.text()).toContain('生成中')
  })

  it('按类型过滤走后端 kind 参数', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.loadHistory('image')
    expect(listTasksMock).toHaveBeenLastCalledWith({ kind: 'image' })
    await vm.loadHistory('')
    expect(listTasksMock).toHaveBeenLastCalledWith(undefined)
  })

  it('存在未决任务时启动自动刷新、全部终态后停止', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mountPage()
      await flushPromises()
      const vm = wrapper.vm as any
      vm.historyTasks = [TASKS[1]] // running
      vm.ensureHistoryPolling()
      expect(vm.historyPollTimer).not.toBeNull()
      listTasksMock.mockResolvedValue({ code: 0, data: { tasks: [TASKS[0]] } })
      // 推进一次刷新后 running 消失 → 定时器清理
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(vm.historyTasks.length).toBe(1)
      expect(vm.historyPollTimer).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

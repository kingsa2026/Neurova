/**
 * AigcHistoryList 契约（迁移自 AIGCPage.history.test.ts）：
 * 账本消费 + kind 过滤 + 状态/错误/下载渲染 + 未决自动刷新、终态自停。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
const listTasksMock = vi.fn()
vi.mock('@/api/modules/generation', () => ({
  generateText: vi.fn(), generateImage: vi.fn(), generateAudio: vi.fn(), submitVideo: vi.fn(),
  listGenerationTasks: (params: any) => listTasksMock(params),
}))
vi.mock('@/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  request: { post: vi.fn(), get: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import AigcHistoryList from '@/components/aigc/AigcHistoryList.vue'
import { makeAigcI18n, AIGC_STUBS } from '@/pages/aigc/__tests__/testUtils'

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
    local_path: '', url: '', source: 'channel', error: '',
  },
  {
    task_id: 't3', kind: 'audio', protocol: 'tts', model: '',
    status: 'failed', prompt: '你好', submitted_at: 1757700200, updated_at: 1757700201,
    local_path: '', url: '', source: 'workflow', error: 'TTS 引擎未就绪',
  },
]

const mountList = (kind?: any) =>
  mount(AigcHistoryList, {
    props: kind ? { kind } : {},
    global: { plugins: [makeAigcI18n()], stubs: AIGC_STUBS },
  })

describe('AigcHistoryList', () => {
  beforeEach(() => {
    listTasksMock.mockReset()
    listTasksMock.mockResolvedValue({ code: 0, data: { tasks: TASKS } })
  })

  it('挂载即拉账本并渲染三类产物 + 错误 + 下载', async () => {
    const wrapper = mountList()
    await flushPromises()
    expect(listTasksMock).toHaveBeenCalled()
    const vm = wrapper.vm as any
    expect(vm.tasks.length).toBe(3)
    expect(wrapper.text()).toContain('一只柴犬')
    expect(wrapper.text()).toContain('TTS 引擎未就绪')
    expect(wrapper.html()).toContain('access_token=tok') // 图像缩略图/下载带凭证
    expect(wrapper.text()).toContain('生成中')
    expect(wrapper.text()).toContain('channel') // 非 rest 来源徽标（工作流/渠道可追溯）
  })

  it('C3：file_missing 记录显示「已过期」且不再渲染缩略图/下载链接', async () => {
    listTasksMock.mockResolvedValue({
      code: 0,
      data: { tasks: [{ ...TASKS[0], url: '', file_missing: true }] },
    })
    const wrapper = mountList()
    await flushPromises()
    expect(wrapper.text()).toContain('已过期')
    // url 已清空：该记录无带凭证的 img/download 链接（不给 404 装可用）
    const html = wrapper.html()
    expect(html).not.toContain('t1_0.png')
  })

  it('kind prop 决定初始过滤', async () => {
    const wrapper = mountList('image')
    await flushPromises()
    expect(listTasksMock).toHaveBeenLastCalledWith({ kind: 'image' })
  })

  it('music kind：过滤联动 + ♪ 图标 + 音频播放器（带凭证）', async () => {
    listTasksMock.mockResolvedValue({
      code: 0,
      data: { tasks: [{
        task_id: 'm1', kind: 'music', protocol: 'fal', model: 'fal-ai/musicgen',
        status: 'succeeded', prompt: '轻快钢琴曲', submitted_at: 1757700300, updated_at: 1757700301,
        local_path: '/data/generations/m1.mp3', url: '/api/v1/generation/files/m1.mp3',
        source: 'rest', error: '',
      }] },
    })
    const wrapper = mountList('music')
    await flushPromises()
    expect(listTasksMock).toHaveBeenLastCalledWith({ kind: 'music' })
    expect(wrapper.text()).toContain('音乐生成') // kind 单选联动文案
    expect(wrapper.text()).toContain('轻快钢琴曲')
    const audio = wrapper.find('audio.aigc-history-audio')
    expect(audio.exists()).toBe(true) // 产物渲染按 music 适配：音频播放器形态
    expect(audio.attributes('src')).toContain('access_token=tok') // 与图像同源凭证
    expect(wrapper.html()).toContain('♪') // 缩略位图标形态
  })

  it('music kind 无产物 url 时不渲染播放器，回退 kind 徽标', async () => {
    listTasksMock.mockResolvedValue({
      code: 0,
      data: { tasks: [{
        task_id: 'm2', kind: 'music', protocol: 'fal', model: '',
        status: 'failed', prompt: '爵士鼓点', submitted_at: 1757700400, updated_at: 1757700401,
        local_path: '', url: '', source: 'workflow', error: '音乐引擎未就绪',
      }] },
    })
    const wrapper = mountList('music')
    await flushPromises()
    expect(wrapper.find('audio.aigc-history-audio').exists()).toBe(false)
    expect(wrapper.html()).toContain('♪') // 无产物仍以音符图标占位（不渲染播放器）
  })

  it('未决任务自动刷新，全部终态自停', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mountList()
      await flushPromises()
      const vm = wrapper.vm as any
      // running 存在 → 5s 自动刷新
      listTasksMock.mockResolvedValue({ code: 0, data: { tasks: [TASKS[0]] } })
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(vm.tasks.length).toBe(1)
      const before = listTasksMock.mock.calls.length
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(listTasksMock.mock.calls.length).toBe(before) // 全终态后不再刷新
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})

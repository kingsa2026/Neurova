/**
 * StudioProjectPage（R4/R5 四 Phase 向导）契约：
 * 进度导轨、拆解触发（runs 轮询）、镜头保存/单镜重试、导出双形态（成片/连播）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ params: { pid: 'p1' }, path: '/aigc/studio/p1' }),
    useRouter: () => ({ push: vi.fn() }),
  }
})
vi.mock('@/utils/security', () => ({
  secureStorage: { get: () => 'tok', set: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/modules/files', () => ({ uploadFile: vi.fn() }))
vi.mock('@/composables/useStudioRun', async (importOriginal) => {
  // 只替掉轮询本体，`describeRunOutcome` 必须用真件：这条测的就是"页面有没有把读数交给
  // 真格式化函数"，连它一起 mock 掉即自证空转。
  const actual = await importOriginal<typeof import('@/composables/useStudioRun')>()
  return {
    ...actual,
    waitStudioRun: vi.fn().mockResolvedValue({ id: 'r1', status: 'done', project_id: 'p1', kind: 'script', detail_json: '{}', error: '' }),
  }
})

vi.mock('@/api/modules/studio', () => ({
  getProject: vi.fn(),
  getEpisode: vi.fn(),
  runSplitScript: vi.fn(),
  runExtract: vi.fn(),
  runStoryboards: vi.fn(),
  runGenerateImages: vi.fn(),
  runGenerateVideos: vi.fn(),
  runNarration: vi.fn(),
  runAssetImages: vi.fn(),
  retryStoryboard: vi.fn(),
  updateStoryboard: vi.fn(),
  updateEpisode: vi.fn(),
  updateAsset: vi.fn(),
  mergeEpisode: vi.fn(),
  addStoryboardManually: vi.fn(),
}))
vi.mock('ant-design-vue', () => ({
  // warning 是真 API 的一员（antd message 有 warning），补齐才不至于把"组件没调它"
  // 这一行为红误报成"mock 少一个键"的类型错。
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import StudioProjectPage from '@/pages/aigc/StudioProjectPage.vue'
import { message } from 'ant-design-vue'
import { waitStudioRun } from '@/composables/useStudioRun'
import {
  getProject, getEpisode, runSplitScript, retryStoryboard, updateStoryboard, mergeEpisode,
  runGenerateImages, runGenerateVideos, runAssetImages,
} from '@/api/modules/studio'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const DETAIL = {
  project: {
    id: 'p1', owner_user_id: 'u1', title: '赘婿龙王', description: '', genre: '都市逆袭',
    style: '国风水墨', aspect_ratio: '9:16 竖屏', total_episodes: 1, status: 'draft',
    thumbnail: '', created_at: 0, updated_at: 0,
  },
  episodes: [
    { id: 'e1', project_id: 'p1', number: 1, title: '受辱', content: '客厅夜', synopsis: '', status: 'draft', duration: 0, video_path: '', subtitle_path: '' },
  ],
  characters: [
    { id: 'c1', project_id: 'p1', name: '林凡', role: 'protagonist', description: '', appearance: '青年男', styling: '', personality: '', final_prompt: '', image_path: '', seed_value: '', status: 'pending' },
  ],
  scenes: [], props: [], runs: [],
}

const SHOT = {
  id: 's1', episode_id: 'e1', number: 1, title: '', description: '主角推门',
  image_prompt: 'man enters', video_prompt: '推门', narration: '他回来了', camera: '中景',
  movement: '固定', atmosphere: '', bgm_prompt: '', sound_effect: '', duration: 3,
  characters_json: '[]', props_json: '[]', first_frame_path: '', injected_prompt: '',
  video_path: '', video_status: 'pending', ledger_task_id: '', subtitle_path: '',
  audio_path: '', status: 'pending', error: '',
}

const mountPage = () =>
  mount(StudioProjectPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { template: '<div><slot /></div>' },
        GlassButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        MentionTextarea: { props: ['modelValue', 'candidates'], template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)"></textarea>' },
        SlideshowPlayer: { props: ['items'], template: '<div class="slideshow-stub">{{ items.length }}</div>' },
        'a-form': { template: '<div><slot /></div>' },
        'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
        'a-textarea': { props: ['value', 'rows'], template: '<textarea :value="value" @input="$emit(\'update:value\', $event.target.value)" />', emits: ['update:value'] },
        'a-input': { props: ['value', 'size', 'placeholder'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />', emits: ['update:value'] },
        'a-input-number': { props: ['value'], template: '<input />', emits: ['update:value'] },
        'a-select': { props: ['options'], template: '<select />', emits: ['update:value'] },
        'a-tag': { template: '<span><slot /></span>' },
        'a-empty': { template: '<div><slot /></div>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-popconfirm': { props: ['title'], template: '<div><slot /></div>' },
      },
    },
  })

describe('StudioProjectPage', () => {
  const getProjectMock = getProject as unknown as ReturnType<typeof vi.fn>
  const getEpisodeMock = getEpisode as unknown as ReturnType<typeof vi.fn>
  const runSplitMock = runSplitScript as unknown as ReturnType<typeof vi.fn>
  const retryMock = retryStoryboard as unknown as ReturnType<typeof vi.fn>
  const updateSbMock = updateStoryboard as unknown as ReturnType<typeof vi.fn>
  const mergeMock = mergeEpisode as unknown as ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    getProjectMock.mockResolvedValue({ code: 0, data: DETAIL })
    getEpisodeMock.mockResolvedValue({ code: 0, data: { episode: DETAIL.episodes[0], storyboards: [SHOT] } })
    runSplitMock.mockResolvedValue({ data: { run_id: 'r1' } })
    retryMock.mockResolvedValue({ data: { run_id: 'r2' } })
    updateSbMock.mockResolvedValue({})
    ;(waitStudioRun as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 'r1', status: 'done', detail_json: '{}', error: '' })
  })

  it('渲染四段进度导轨 + 项目信息', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('剧情创作')
    expect(text).toContain('场景角色')
    expect(text).toContain('AI 工作台')
    expect(text).toContain('制片导出')
    expect(text).toContain('赘婿龙王')
  })

  it('Phase01 拆解：runSplitScript → 轮询 run → 刷新详情', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.novel = '三年之期已到'
    await vm.splitScript()
    await flushPromises()
    expect(runSplitMock).toHaveBeenCalledWith('p1', '三年之期已到', undefined)
    expect(waitStudioRun).toHaveBeenCalledWith('p1', 'r1')
    expect(getProjectMock).toHaveBeenCalled()
  })

  it('带病完成落警示条并点名条数（detail_json 的读数有真读者）', async () => {
    // §6-87：改前这条走的是 message.success('任务完成')——服务端写的条数在界面上等于没写
    ;(waitStudioRun as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'r1', status: 'done_with_fallback', project_id: 'p1', kind: 'videos',
      detail_json: '{"submitted":4,"fallback_failed":1,"fallback_blocked":2,"fallback":""}',
      error: '',
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.novel = '三年之期已到'
    await vm.splitScript()
    await flushPromises()
    const warned = (message.warning as unknown as ReturnType<typeof vi.fn>).mock.calls.flat()
    expect(warned.join('')).toContain('任务带病完成')
    expect(warned.join('')).toContain('1 项失败')
    expect(warned.join('')).toContain('2 项被阻断')
    expect(message.success).not.toHaveBeenCalled()
  })

  it('Phase03 镜头卡片渲染 + 保存透传 @角色映射', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('workbench')
    await flushPromises()
    expect(wrapper.text()).toContain('主角推门')
    await vm.saveShot(SHOT, [{ name: '林凡', id: 'c1' }])
    const args = updateSbMock.mock.calls.at(-1) ?? []
    expect(args[0]).toBe('s1')
    expect(args[1].characters).toEqual([{ name: '林凡', id: 'c1' }])
  })

  it('镜头面读出 title 与注入后的成品提示词（injected_prompt 有读者）', async () => {
    // §6-89：`injected_prompt` 由首帧生成时写进行（services.py 唯一写点），改前全仓零读者
    // ——@角色注入后到底喂给模型什么，事后一行都回看不了；`title` 同形（拆解写入，镜头卡只渲染 description）。
    getEpisodeMock.mockResolvedValue({
      code: 0,
      data: {
        episode: DETAIL.episodes[0],
        storyboards: [{
          ...SHOT, title: '雨夜对峙', image_prompt: 'man enters',
          injected_prompt: '林凡（青年男，黑色风衣）推门而入，冷色调',
        }],
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('workbench')
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('雨夜对峙')
    expect(text).toContain('林凡（青年男，黑色风衣）推门而入，冷色调')
    expect(text).toContain('实际注入提示词')
  })

  it('单镜重试 stage=image 走 retryStoryboard', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('workbench')
    await flushPromises()
    await vm.retryShot(SHOT, 'image')
    expect(retryMock).toHaveBeenCalledWith('s1', expect.objectContaining({ stage: 'image' }))
  })

  it('A1 尾帧：按钮文案随 end_frame_path 切换 + applyShotEndFrame 透传', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('workbench')
    await flushPromises()
    // 无尾帧 → 「设为尾帧」
    expect(wrapper.text()).toContain('设为尾帧')
    // 有尾帧 → 缩略图 + 「更换尾帧」
    const withEnd = { ...SHOT, end_frame_path: 'data\\generations\\tail.png' }
    getEpisodeMock.mockResolvedValue({ code: 0, data: { episode: DETAIL.episodes[0], storyboards: [withEnd] } })
    await vm.loadStoryboards()
    expect(wrapper.text()).toContain('更换尾帧')
    // R2 诚实呈现：设置尾帧后显示能力提示（WAN 默认通道记为忽略项）
    expect(wrapper.text()).toContain('仅支持首尾帧插值的通道')
    // applyShotEndFrame → updateStoryboard(s1, { end_frame_path }) 并刷新
    await vm.applyShotEndFrame(SHOT, 'data/generations/tail.png')
    await flushPromises()
    expect(updateSbMock).toHaveBeenCalledWith('s1', { end_frame_path: 'data/generations/tail.png' })
    // fileUrlOf：Windows 反斜杠路径取文件名 + 鉴权 token
    expect(vm.fileUrlOf('data\\generations\\tail.png')).toBe('/api/v1/generation/files/tail.png?access_token=tok')
    expect(vm.fileUrlOf('')).toBe('')
  })


  it('模型选择透传：auto 不传参（后端能力路由），选定模型带 model+provider_id', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.genImages()
    await flushPromises()
    expect((runGenerateImages as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]).toEqual({})
    vm.imgModel = 'flux.1'
    await vm.genImages()
    const call = (runGenerateImages as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]
    expect(call).toEqual({ model: 'flux.1' }) // mock 列表无 providerOf 命中 → provider_id undefined 不入体
    await vm.genVideos()
    expect((runGenerateVideos as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]).toEqual({ resolution: '720p' })
    await vm.batchAssetImages()
    // 资产定妆与首帧共享 imgModel 选择
    expect((runAssetImages as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]).toEqual({ model: 'flux.1', ids: undefined })
  })
  it('A3：BGM 上传状态 → merge 透传 bgm_path', async () => {
    mergeMock.mockResolvedValue({ code: 0, data: { ok: true, composed: true, mode: 'ffmpeg_concat', url: '/api/v1/generation/files/m1.mp4', bgm_mixed: true, merge: { id: 'm1' }, items: [] } })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('export')
    await flushPromises()
    expect(wrapper.text()).toContain('上传 BGM')
    vm.bgmPath = 'uploads/bg.mp3'
    await vm.doMerge()
    await flushPromises()
    expect(mergeMock).toHaveBeenCalledWith(expect.any(String), { bgm_path: 'uploads/bg.mp3' })
  })

  it('Phase04 导出：成片 URL 与连播清单双形态', async () => {
    mergeMock.mockResolvedValue({
      code: 0,
      data: {
        ok: true, composed: true, mode: 'ffmpeg_concat', url: '/api/v1/generation/files/m1.mp4',
        // A5：诚实降级标注（无中文字体不假烧录，warning 原文上屏）
        subtitle_burned: false, warning: '本机缺少中文字体，未烧录字幕（播放器可外挂 SRT 字幕文件）',
        merge: { id: 'm1' }, items: [],
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('export')
    await vm.doMerge()
    await flushPromises()
    expect(vm.composedUrl).toBe('/api/v1/generation/files/m1.mp4')
    expect(wrapper.html()).toContain('access_token=tok')
    expect(wrapper.find('.studio-merge-warn').text()).toContain('中文字体')

    mergeMock.mockResolvedValue({
      code: 0,
      data: {
        ok: true, composed: false, mode: 'slideshow_manifest', merge: { id: 'm2' },
        items: [{ index: 1, shot: 1, image: '/f/a.png', audio: '', video: '', text: '他回来了' }],
      },
    })
    await vm.doMerge()
    await flushPromises()
    expect(wrapper.find('.slideshow-stub').exists()).toBe(true)
  })
})

/**
 * §6-78 F 条：Phase03 视频刷新定时器的**启停必须同源**。
 *
 * 改前的三格都是同一件事的三个断面——「停表」没有入口，只有「读到 running 才起表」：
 * ① `loadStoryboards` 失败分支把列表清空却不重判启停 → 无数据可停时 5s 表继续无限打 GET；
 * ② `switchPhase` 不停表 → 镜头卡片已被 `v-if` 摘掉，页面仍在后台每 5s 拉一次整集；
 * ③ `retryShot` 不走 `track()` 而是发一次性 `setTimeout(3000)` → 提交发生在服务端后台任务里，
 *    3s 时读到的常是旧态，`running` 永不成立，周期表根本不启，直到用户手动切一次 phase 才复活。
 */
describe('Phase03 视频刷新定时器（H2-4 · F 条）', () => {
  const getProjectMock = getProject as unknown as ReturnType<typeof vi.fn>
  const getEpisodeMock = getEpisode as unknown as ReturnType<typeof vi.fn>
  const retryMock = retryStoryboard as unknown as ReturnType<typeof vi.fn>
  const waitMock = waitStudioRun as unknown as ReturnType<typeof vi.fn>

  const RUNNING_SHOT = { ...SHOT, video_status: 'running' }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    getProjectMock.mockResolvedValue({ code: 0, data: DETAIL })
    getEpisodeMock.mockResolvedValue({
      code: 0, data: { episode: DETAIL.episodes[0], storyboards: [RUNNING_SHOT] },
    })
    retryMock.mockResolvedValue({ code: 0, data: { run_id: 'r2' } })
    waitMock.mockResolvedValue({ id: 'r2', status: 'done', detail_json: '{}', error: '' })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('读失败即停表：列表被清空后不再无限打 GET', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(getEpisodeMock.mock.calls.length).toBeGreaterThan(0)

    getEpisodeMock.mockRejectedValue(new Error('网络中断'))
    await vi.advanceTimersByTimeAsync(5000)   // 触发起表的那一跳，走失败分支
    const afterFailure = getEpisodeMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(20000)   // 若没停表，这里会再打 4 次
    expect(getEpisodeMock.mock.calls.length).toBe(afterFailure)
    expect((wrapper.vm as any).storyboards).toEqual([])
    wrapper.unmount()
  })

  it('离开工作台即停表：卡片已摘掉就不该还在后台拉整集', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.switchPhase('export')
    const afterLeave = getEpisodeMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(20000)
    expect(getEpisodeMock.mock.calls.length).toBe(afterLeave)
    wrapper.unmount()
  })

  it('单镜重试走 track 轮询，定时器由真状态决定而非 3s 盲刷', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const before = getEpisodeMock.mock.calls.length
    const vm = wrapper.vm as any
    await vm.retryShot(RUNNING_SHOT, 'video')
    await flushPromises()

    // 重试的 run 必须交回同一个轮询入口（改前这里根本没有 track）
    expect(waitMock).toHaveBeenCalledWith('p1', 'r2')
    // 重读后镜头仍是 running → 周期表应当是活的（改前只有那一次性 3s）
    await vi.advanceTimersByTimeAsync(5000)
    expect(getEpisodeMock.mock.calls.length).toBeGreaterThan(before)
    wrapper.unmount()
  })
})

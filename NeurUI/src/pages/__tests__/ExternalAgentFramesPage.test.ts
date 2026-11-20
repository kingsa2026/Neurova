/**
 * ExternalAgentFramesPage — 外部代理帧回放调试视图（F2 帧账本读面前端）。
 *
 * 覆盖：非 admin 先行拦截（不发请求）、空 ID 警告、加载渲染帧行
 * （seq/方向/类型/载荷摘要）、游标翻页（after_seq 取末条 seq）、
 * 失败诚实展示错误。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/neuacp', () => ({
  fetchNeuacpRunFrames: vi.fn(),
  fetchNeuacpCatalog: vi.fn(),
  testNeuacpConnection: vi.fn(),
  fetchNeuacpStatus: vi.fn(),
  removeTeamMember: vi.fn(),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import ExternalAgentFramesPage from '../ExternalAgentFramesPage.vue'
import { fetchNeuacpRunFrames } from '@/api/modules/neuacp'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import zhCN from '@/i18n/locales/zh-CN'

const FRAMES_PAGE = {
  subagent_id: 'swarm_abc',
  count: 2,
  frames: [
    {
      seq: 1,
      subagent_id: 'swarm_abc',
      direction: 'out',
      frame: { type: 'argv', command: ['zcode', '--prompt', '任务'] },
      occurred_at: '2026-11-20T10:00:00+00:00',
    },
    {
      seq: 2,
      subagent_id: 'swarm_abc',
      direction: 'in',
      frame: { type: 'assistant', message: { content: [{ type: 'text', text: '答案' }] } },
      occurred_at: '2026-11-20T10:00:01+00:00',
    },
  ],
}

const stubs = {
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="glass-btn" @click="$emit(\'click\')"><slot /></button>',
  },
  'a-input': { props: ['value', 'placeholder'], template: '<input class="a-input" />' },
}

function mountPage(role: 'admin' | 'user' = 'admin') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const authStore = useAuthStore()
  authStore.user = {
    id: 'u-1',
    username: 'tester',
    email: 't@n.io',
    role,
    status: 'active',
    allowed_modules: [],
  } as any
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
  return mount(ExternalAgentFramesPage, {
    global: { plugins: [i18n, pinia], stubs },
  })
}

function mockPage(frames: any[] = FRAMES_PAGE.frames) {
  ;(fetchNeuacpRunFrames as ReturnType<typeof vi.fn>).mockResolvedValue({
    subagent_id: 'swarm_abc',
    count: frames.length,
    frames,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ExternalAgentFramesPage — 帧回放调试视图', () => {
  it('非 admin 先行拦截：只显示提示，不发请求', async () => {
    const w = mountPage('user')
    await flushPromises()
    expect(w.text()).toContain('帧回放仅限管理员')
    expect(fetchNeuacpRunFrames).not.toHaveBeenCalled()
  })

  it('空 ID 点加载只警告，不发请求', async () => {
    const w = mountPage('admin')
    await flushPromises()
    await (w.vm as any).loadFrames(true)
    expect(message.warning).toHaveBeenCalled()
    expect(fetchNeuacpRunFrames).not.toHaveBeenCalled()
  })

  it('加载渲染帧行（seq/方向/类型/载荷摘要）', async () => {
    const w = mountPage('admin')
    await flushPromises()
    mockPage()
    ;(w.vm as any).subagentId = 'swarm_abc'
    await (w.vm as any).loadFrames(true)
    await flushPromises()
    expect(fetchNeuacpRunFrames).toHaveBeenCalledWith('swarm_abc', 0, 200)
    expect(w.text()).toContain('#1')
    expect(w.text()).toContain('argv')
    expect(w.text()).toContain('assistant')
    expect(w.text()).toContain('out')
    expect(w.text()).toContain('in')
  })

  it('游标翻页：续页以已加载末条 seq 起并追加', async () => {
    const w = mountPage('admin')
    await flushPromises()
    mockPage()
    ;(w.vm as any).subagentId = 'swarm_abc'
    await (w.vm as any).loadFrames(true)
    const lastSeq = FRAMES_PAGE.frames[FRAMES_PAGE.frames.length - 1].seq
    mockPage([
      {
        seq: 3,
        subagent_id: 'swarm_abc',
        direction: 'observed',
        frame: { type: 'exited', exit_code: 0 },
        occurred_at: '2026-11-20T10:00:02+00:00',
      },
    ])
    await (w.vm as any).loadFrames(false)
    expect(fetchNeuacpRunFrames).toHaveBeenLastCalledWith('swarm_abc', lastSeq, 200)
    expect((w.vm as any).frames).toHaveLength(3)
  })

  it('读取失败诚实展示错误', async () => {
    const w = mountPage('admin')
    await flushPromises()
    ;(fetchNeuacpRunFrames as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('404 not found'))
    ;(w.vm as any).subagentId = 'swarm_abc'
    await (w.vm as any).loadFrames(true)
    expect(w.text()).toContain('404 not found')
    expect(message.error).toHaveBeenCalled()
  })
})

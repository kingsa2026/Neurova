import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('@/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/api/modules/console', () => ({
  deleteConsoleSession: vi.fn(),
  archiveConsoleSession: vi.fn(),
  unarchiveConsoleSession: vi.fn(),
  getConsoleSessionTimeline: vi.fn(),
}))

vi.mock('@/bus', () => ({
  default: { on: vi.fn(), off: vi.fn(), emit: vi.fn(), clear: vi.fn() },
}))

import api from '@/api'
import { getConsoleSessionTimeline } from '@/api/modules/console'
import { useChat } from '@/composables/useChat'

const SESSIONS = {
  data: {
    sessions: [
      { session_id: 's-newest', title: '最新', created_at: '2026-03-01' },
      { session_id: 's-old', title: '旧会话', created_at: '2026-01-01' },
    ],
  },
}

/** 按 URL 前缀分派，不用 mockResolvedValueOnce 排队——那条路径一多调用顺序就脆。 */
function stubRoutes(routes: Record<string, unknown>) {
  vi.mocked(api.get).mockImplementation((async (url: string) => {
    const key = Object.keys(routes).find((k) => String(url).startsWith(k))
    return key ? routes[key] : { data: {} }
  }) as any)
}

function historyUrlRequested(): string {
  const call = vi
    .mocked(api.get)
    .mock.calls.find((c) => String(c[0]).startsWith('/console/chat/history'))
  return call ? String(call[0]) : ''
}

describe('刷新/断连后的会话找回与时间线补课', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    stubRoutes({ '/console/chat/sessions': SESSIONS, '/console/chat/history': { data: { messages: [] } } })
    vi.mocked(getConsoleSessionTimeline).mockResolvedValue({ data: { events: [] } } as any)
  })

  it('auto-select 也走时间线补课（刷新路径此前绕过它）', async () => {
    const { loadSessions } = useChat()
    await loadSessions('agent-1')

    expect(getConsoleSessionTimeline).toHaveBeenCalledTimes(1)
    expect(vi.mocked(getConsoleSessionTimeline).mock.calls[0][0]).toBe('s-newest')
  })

  it('优先回到上次打开的那条，而不是盲取列表首位', async () => {
    localStorage.setItem('nr_last_session', 's-old')
    const { loadSessions } = useChat()
    await loadSessions('agent-1')

    expect(historyUrlRequested()).toContain('session_id=s-old')
  })

  it('记忆中的会话不在当前列表时退回首位（切 agent 的兜底）', async () => {
    localStorage.setItem('nr_last_session', 'ghost-from-another-agent')
    const { loadSessions } = useChat()
    await loadSessions('agent-1')

    expect(historyUrlRequested()).toContain('session_id=s-newest')
  })

  it('切换成功才记下这条为上次会话', async () => {
    const { switchSession } = useChat()
    await switchSession('s-old')

    expect(localStorage.getItem('nr_last_session')).toBe('s-old')
  })

  it('切换失败不写记忆（不把没打开成的记成上次会话）', async () => {
    stubRoutes({
      '/console/chat/history': Promise.reject(new Error('HTTP 500')),
    })
    const { switchSession } = useChat()
    const result = await switchSession('s-old')

    expect(result.ok).toBe(false)
    expect(localStorage.getItem('nr_last_session')).toBeFalsy()
  })
})

describe('「本轮仍在生成中」文案 11 语齐全', () => {
  const LOCALES = [
    'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'fr-FR',
    'es-ES', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
  ]

  LOCALES.forEach((loc) => {
    it(`${loc} 有 chat.turnStillRunning 且非空`, async () => {
      const mod = await import(`@/i18n/locales/${loc}.ts`)
      const value = mod.default?.chat?.turnStillRunning
      expect(typeof value).toBe('string')
      expect((value || '').trim().length).toBeGreaterThan(0)
    })
  })
})

describe('首轮中途刷新：开局认领的会话必须找回得到', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    stubRoutes({
      '/console/chat/sessions': SESSIONS,
      '/console/chat/history': { data: { messages: [] } },
    })
    vi.mocked(getConsoleSessionTimeline).mockResolvedValue({ data: { events: [] } } as any)
  })

  // 实测由来（2026-10-26 真浏览器）：新会话的 id 过去只在 done 帧回传，首轮流式
  // 期间前端手里是空——中途刷新后回到的是"上一个会话"，正在跑的那一轮既看不见
  // 也找不回；断线重连还会以空 id 让服务端另起一个 0 消息空会话。
  it('rememberSession 与 switchSession 写同一把键（不另起第二份记忆）', async () => {
    const { rememberSession, switchSession } = useChat()
    rememberSession('s-live')
    expect(localStorage.getItem('nr_last_session')).toBe('s-live')

    await switchSession('s-old')
    expect(localStorage.getItem('nr_last_session')).toBe('s-old')
  })

  it('空 id 不写记忆（没认领到的会话不能把上次记忆擦掉）', () => {
    const { rememberSession } = useChat()
    rememberSession('s-live')
    rememberSession('')
    expect(localStorage.getItem('nr_last_session')).toBe('s-live')
  })

  it('开局认领过的会话，刷新后 auto-select 回到它而不是首位', async () => {
    localStorage.setItem('nr_last_session', 's-live')
    stubRoutes({
      '/console/chat/sessions': {
        data: {
          sessions: [
            { session_id: 's-newest', title: '别轮', created_at: '2026-03-01' },
            { session_id: 's-live', title: '正在跑的这一轮', created_at: '2026-01-01' },
          ],
        },
      },
      '/console/chat/history': { data: { messages: [] } },
    })
    const { loadSessions } = useChat()
    await loadSessions('agent-1')
    expect(historyUrlRequested()).toContain('s-live')
  })
})

describe('开局 session 帧的前端接线（源码契约）', () => {
  // ChatPage 体量过大不便整体挂载，与 ChatPage.parkedSurface.test.ts 同一取舍。
  const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')

  it('session 帧有分支，且认领只有一处实现', () => {
    expect(source).toMatch(/case 'session':/)
    const adoptSites = source.split('adoptStreamedSession(').length - 1
    // 1 处定义 + 2 处调用（session 帧与 done 帧共用同一处认领）；再增即为第二份实现
    expect(adoptSites).toBe(3)
    expect(source).toMatch(/function adoptStreamedSession\(/)
  })

  it('认领当场写会话记忆，且旧的内联四步不再留着第二份', () => {
    expect(source).toMatch(/rememberSession\(sid\)/)
    const inlinedAdd = source.match(/if \(!currentSessionId\.value && event\.session_id\)/)
    expect(inlinedAdd).toBeNull()
  })
})

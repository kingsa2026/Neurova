/**
 * 控制台会话时间线端点契约测试（红灯切片）。
 *
 * Issue #262：`GET /console/chat/sessions/{sid}/timeline` 已建但前端零消费者。
 * 本文件钉住前端请求形态（URL / 查询参数），保证与后端
 * `neurova/api/endpoints/console.py::get_console_session_timeline` 的契约一致。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: { events: [], total: 0 } }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import api from '@/api'
import { getConsoleSessionTimeline, getConsoleChatHistory } from '@/api/modules/console'

const mockGet = vi.mocked(api.get)

describe('getConsoleSessionTimeline', () => {
  beforeEach(() => vi.clearAllMocks())

  it('无 limit 时不带查询参数', async () => {
    await getConsoleSessionTimeline('s-1')
    expect(mockGet).toHaveBeenCalledWith('/console/chat/sessions/s-1/timeline')
  })

  it('limit 作为查询参数下发', async () => {
    await getConsoleSessionTimeline('s-1', 200)
    expect(mockGet).toHaveBeenCalledWith('/console/chat/sessions/s-1/timeline?limit=200')
  })

  it('sessionId 需 URL 编码（防路径注入）', async () => {
    await getConsoleSessionTimeline('a/b c')
    expect(mockGet).toHaveBeenCalledWith('/console/chat/sessions/a%2Fb%20c/timeline')
  })

  it('limit<=0 视为「全量」，不带参数', async () => {
    await getConsoleSessionTimeline('s-1', 0)
    expect(mockGet).toHaveBeenCalledWith('/console/chat/sessions/s-1/timeline')
  })
})

describe('getConsoleChatHistory（既有端点，回归锚点）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('history 与 timeline 走同族路径', async () => {
    await getConsoleChatHistory('s-1')
    expect(mockGet).toHaveBeenCalledWith('/console/chat/history?session_id=s-1')
  })
})

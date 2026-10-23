/**
 * 质量事件 API 契约：路径与载荷必须与后端 `/v1/quality` 端点一致。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import api from '@/api'
import {
  getQualityMetrics,
  getSessionTakeoverState,
  recordHumanTakeover,
} from '@/api/modules/quality'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

describe('quality API contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('接管事件走 /quality/outcomes，控制台标记 source=console_mark', async () => {
    await recordHumanTakeover({
      event_type: 'human_takeover_started',
      session_id: 's-1',
      agent_id: 'a-1',
      source: 'console_mark',
      reason_code: 'console_toggle',
    })
    expect(mockPost).toHaveBeenCalledWith('/quality/outcomes', {
      event_type: 'human_takeover_started',
      session_id: 's-1',
      agent_id: 'a-1',
      source: 'console_mark',
      reason_code: 'console_toggle',
    })
  })

  it('接管状态按会话读取且 sessionId 做 URL 编码', async () => {
    await getSessionTakeoverState('a/b c')
    expect(mockGet).toHaveBeenCalledWith('/quality/sessions/a%2Fb%20c/takeover')
  })

  it('质量指标窗口以 window_seconds 下发', async () => {
    await getQualityMetrics(86400)
    expect(mockGet).toHaveBeenCalledWith('/quality/metrics', {
      params: { window_seconds: 86400 },
    })
  })
})

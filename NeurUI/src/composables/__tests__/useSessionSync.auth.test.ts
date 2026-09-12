/**
 * useSessionSync 鉴权契约测试（S-03 WS token 契约的前端适配，2026-09-12）
 *
 * 后端 /api/v1/sync/ws/{session_id} 强制 ?token=<JWT>（S-03，user_id 从
 * token 主体派生）。此前前端 buildUrl 从不携带 token → 每次连接必被
 * 拒绝；后端曾以"accept 前 close"拒绝握手被浏览器报成 403，根修后为
 * accept → close(4401)。
 *
 * 前端契约：
 * - buildUrl 携带 ?token=<JWT>，与 axios Authorization 同源（secureStorage auth_token）
 * - token 缺失时不带 token 参数（后端 4401，行为可预期）
 * - close 4401 = 鉴权失败（非瞬态）：停止重连，避免无限 4401 循环
 * - 非 4401 关闭（网络抖动等）：保持既有指数退避重连
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useSessionSync } from '@/composables/useSessionSync'

const { secureStorageGet } = vi.hoisted(() => ({ secureStorageGet: vi.fn() }))

vi.mock('@/utils/security', () => ({
  secureStorage: {
    get: (...args: unknown[]) => secureStorageGet(...args),
    set: vi.fn(),
    remove: vi.fn(),
  },
}))

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  url: string
  readyState = FakeWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((evt: { data: string }) => void) | null = null
  onclose: ((evt: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close(code = 1005) {
    this.onclose?.({ code })
  }
  open() {
    this.onopen?.()
  }
}

function lastWs(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

describe('useSessionSync 鉴权契约', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
    FakeWebSocket.instances = []
    secureStorageGet.mockReturnValue('test-jwt-token.abc.def')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('buildUrl 携带 token（与 axios 同源凭据）', () => {
    const sid = ref('s1')
    useSessionSync(() => sid.value, () => {})
    const url = lastWs().url
    expect(url).toContain('/sync/ws/s1?')
    expect(url).toContain('token=test-jwt-token.abc.def')
    expect(url).toMatch(/channel_type=web-chat-/)
  })

  it('token 缺失时不带 token 参数', () => {
    secureStorageGet.mockReturnValue(null)
    const sid = ref('s1')
    useSessionSync(() => sid.value, () => {})
    expect(lastWs().url).not.toContain('token=')
  })

  it('close 4401（鉴权失败）停止重连', () => {
    const st = vi.spyOn(globalThis, 'setTimeout')
    const sid = ref('s1')
    useSessionSync(() => sid.value, () => {})
    const ws = lastWs()
    ws.open()
    st.mockClear()
    ws.close(4401)
    expect(st).not.toHaveBeenCalled()
    expect(FakeWebSocket.instances.length).toBe(1)
  })

  it('非 4401 关闭保持重连（网络抖动语义不变）', () => {
    const st = vi.spyOn(globalThis, 'setTimeout')
    const sid = ref('s1')
    useSessionSync(() => sid.value, () => {})
    lastWs().close(1006)
    expect(st).toHaveBeenCalled()
  })
})

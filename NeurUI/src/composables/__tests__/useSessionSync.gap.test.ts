/**
 * useSessionSync gap 检测测试（OpenOcta 启发 P0-1：WS 单调 seq + 前端 gap 检测）。
 *
 * 服务端 sync WS 每个事件帧携带 per-session 单调 seq（session_sync_manager
 * add_event 盖章）；连接建立时服务端先发 sync_hello{next_seq}（纪元探测），
 * 重连时客户端带游标发 sync_resume{last_seq} 定向补发。
 *
 * 前端契约：
 * - seq 连续递增 → 正常投递
 * - seq > lastSeq+1 → 触发 onGap(missed, lastSeq)，事件本身仍投递
 * - seq <= lastSeq（本连接内重复/重放）→ 跳过投递（去重）
 * - 无 seq 帧（heartbeat_ack/message_sent 等控制帧）→ 不影响游标
 * - sync_hello.next_seq <= 游标 → 服务端纪元更迭（后端重启 seq 归零）→ 重置游标，
 *   避免重启后所有新帧被当作旧帧静默丢弃
 * - 会话切换 → 游标清零，跨会话不误报
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useSessionSync, type SessionSyncEvent } from '@/composables/useSessionSync'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  url: string
  readyState = FakeWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((evt: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.onclose?.()
  }
  open() {
    this.onopen?.()
  }
  emit(frame: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

function lastWs(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

function evt(seq: number, event_type = 'subagent_chunk'): Record<string, unknown> {
  return { seq, event_type, event_id: `evt_${seq}`, session_id: 's1', payload: { n: seq } }
}

describe('useSessionSync gap 检测', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
    FakeWebSocket.instances = []
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('连续 seq 正常投递，不触发 gap', () => {
    const seen: number[] = []
    const onGap = vi.fn()
    const sid = ref('s1')
    useSessionSync(() => sid.value, e => seen.push(e.seq as number), { onGap })
    const ws = lastWs()
    ws.open()
    ws.emit(evt(1))
    ws.emit(evt(2))
    ws.emit(evt(3))
    expect(seen).toEqual([1, 2, 3])
    expect(onGap).not.toHaveBeenCalled()
  })

  it('seq 跳号触发 onGap(missed)，事件本身仍投递', () => {
    const seen: number[] = []
    const onGap = vi.fn()
    const sid = ref('s1')
    useSessionSync(() => sid.value, e => seen.push(e.seq as number), { onGap })
    const ws = lastWs()
    ws.open()
    ws.emit(evt(1))
    ws.emit(evt(2))
    ws.emit(evt(5)) // 丢 3、4
    expect(seen).toEqual([1, 2, 5])
    expect(onGap).toHaveBeenCalledTimes(1)
    expect(onGap).toHaveBeenCalledWith(2, 2)
  })

  it('无 seq 控制帧不影响游标', () => {
    const seen: number[] = []
    const onGap = vi.fn()
    const sid = ref('s1')
    useSessionSync(() => sid.value, e => seen.push(e.seq as number), { onGap })
    const ws = lastWs()
    ws.open()
    ws.emit({ type: 'heartbeat_ack' })
    ws.emit({ type: 'message_sent', event_id: 'x' })
    ws.emit(evt(1))
    ws.emit({ type: 'heartbeat_ack' })
    ws.emit(evt(2))
    expect(seen).toEqual([1, 2])
    expect(onGap).not.toHaveBeenCalled()
  })

  it('重连保留游标：旧帧去重，新帧补投', () => {
    vi.useFakeTimers()
    try {
      const seen: number[] = []
      const onGap = vi.fn()
      const sid = ref('s1')
      useSessionSync(() => sid.value, e => seen.push(e.seq as number), { onGap })
      const first = lastWs()
      first.open()
      first.emit(evt(48))
      first.emit(evt(49))
      first.emit(evt(50))
      expect(seen).toEqual([48, 49, 50])

      // 服务端断开 → 客户端自动重连（退避 1s）
      first.onclose?.()
      vi.advanceTimersByTime(10_000) // 退避封顶（retry=1 → 2s，取上限稳健）
      const second = lastWs()
      expect(second).not.toBe(first)

      // 重连：服务端纪元未变（next_seq=53 > 游标 50），重放 48~52 + 新帧
      second.open()
      second.emit({ type: 'sync_hello', next_seq: 53 })
      second.emit(evt(48))
      second.emit(evt(50))
      second.emit(evt(51))
      second.emit(evt(52))
      second.emit(evt(53))
      // 48/50 已见过跳过；51/52/53 连续补投；无 gap 误报
      expect(seen).toEqual([48, 49, 50, 51, 52, 53])
      expect(onGap).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('重连发 sync_resume{last_seq} 定向补发请求', () => {
    vi.useFakeTimers()
    try {
      const sid = ref('s1')
      useSessionSync(() => sid.value, () => {}, { onGap: () => {} })
      const first = lastWs()
      first.open()
      first.emit(evt(7))
      first.onclose?.()
      vi.advanceTimersByTime(10_000) // 退避封顶（retry=1 → 2s，取上限稳健）
      const second = lastWs()
      second.open()
      const resumes = second.sent
        .map(s => JSON.parse(s))
        .filter(m => m.type === 'sync_resume')
      expect(resumes).toEqual([{ type: 'sync_resume', last_seq: 7 }])
    } finally {
      vi.useRealTimers()
    }
  })

  it('sync_hello 纪元更迭（后端重启 seq 归零）→ 重置游标，新帧不被误吞', () => {
    vi.useFakeTimers()
    try {
      const seen: number[] = []
      const onGap = vi.fn()
      const sid = ref('s1')
      useSessionSync(() => sid.value, e => seen.push(e.seq as number), { onGap })
      const first = lastWs()
      first.open()
      first.emit(evt(1))
      first.emit(evt(2))
      first.emit(evt(3))
      expect(seen).toEqual([1, 2, 3])

      first.onclose?.()
      vi.advanceTimersByTime(10_000) // 退避封顶（retry=1 → 2s，取上限稳健）
      const second = lastWs()
      second.open()
      // 后端已重启：会话重建，next_seq=1（<= 游标 3）→ 纪元更迭
      second.emit({ type: 'sync_hello', next_seq: 1 })
      second.emit(evt(1))
      second.emit(evt(2))
      expect(seen).toEqual([1, 2, 3, 1, 2])
      expect(onGap).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('会话切换重置游标，跨会话不误报 gap', async () => {
    const seen: string[] = []
    const onGap = vi.fn()
    const sid = ref('s1')
    useSessionSync(() => sid.value, e => seen.push(String(e.payload?.n)), { onGap })
    lastWs().open()
    lastWs().emit(evt(1))
    lastWs().emit(evt(2))

    sid.value = 's2'
    await nextTick() // watch 回调异步 flush
    const ws2 = lastWs()
    expect(ws2.url).toContain('/sync/ws/s2')
    ws2.open()
    ws2.emit(evt(1))
    ws2.emit(evt(2))
    expect(seen).toEqual(['1', '2', '1', '2'])
    expect(onGap).not.toHaveBeenCalled()
  })

  it('未提供 onGap（旧调用方签名）不崩', () => {
    const sid = ref('s1')
    useSessionSync(() => sid.value, () => {})
    const ws = lastWs()
    ws.open()
    ws.emit(evt(1))
    ws.emit(evt(9)) // gap 但无回调
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

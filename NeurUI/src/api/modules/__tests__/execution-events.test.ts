import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock 依赖（与 api-modules.test.ts 同模式）
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))
vi.mock('@/config', () => ({ default: { apiBaseUrl: 'http://test:9527/api' } }))
vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn().mockReturnValue('test-token'), set: vi.fn(), remove: vi.fn() },
}))

import { subscribeExecutionEvents, type ExecutionEventFrame } from '../collaboration'

// ---------------------------------------------------------------------------
// fetch+ReadableStream SSE 测试基建：可编程的响应体
// ---------------------------------------------------------------------------

function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  let i = 0
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]))
        i++
      } else {
        controller.close()
      }
    },
  })
  return new Response(body, { status: 200 })
}

describe('subscribeExecutionEvents', () => {
  const fetchSpy = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchSpy)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('解析 SSE 帧并回调事件（含中文与 keep-alive 忽略）', async () => {
    const frames: ExecutionEventFrame[] = [
      { seq: 1, type: 'workflow_started', workflow_id: 'wf', execution_id: 'e1', data: {}, timestamp: 1 },
      { seq: 2, type: 'node_started', workflow_id: 'wf', execution_id: 'e1', node_id: 'n0', data: {}, timestamp: 2 },
      { seq: 3, type: 'node_completed', workflow_id: 'wf', execution_id: 'e1', node_id: 'n0', data: { result: { status: 'success', output: '结果中文' } }, timestamp: 3 },
    ]
    fetchSpy.mockResolvedValue(
      sseResponse([
        'data: ' + JSON.stringify(frames[0]) + '\n\n',
        ': keep-alive\n\n', // 注释行应被忽略
        'data: ' + JSON.stringify(frames[1]) + '\n\n',
        'data: ' + JSON.stringify(frames[2]) + '\n\n', // 跨 chunk 不拼接也能按行解析
      ]),
    )

    const received: ExecutionEventFrame[] = []
    const close = subscribeExecutionEvents('e1', f => received.push(f))

    // 等流读完
    await vi.waitFor(() => expect(received.length).toBe(3))

    expect(received.map(f => f.type)).toEqual(['workflow_started', 'node_started', 'node_completed'])
    expect((received[2].data.result as { output: string }).output).toBe('结果中文')
    close()
  })

  it('URL 带 after 游标与 Bearer 头', async () => {
    fetchSpy.mockClear()
    fetchSpy.mockResolvedValue(sseResponse([]))
    const close = subscribeExecutionEvents('exec9', () => {}, { after: 7 })
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const [url, init] = fetchSpy.mock.calls.at(-1)!
    expect(url).toBe('http://test:9527/api/neurflow/executions/exec9/events?after=7')
    expect((init as RequestInit).headers).toMatchObject({ Authorization: 'Bearer test-token' })
    close()
  })

  it('非 200 响应不回调且不抛错', async () => {
    fetchSpy.mockResolvedValue(new Response('forbidden', { status: 403 }))
    const onEvent = vi.fn()
    const close = subscribeExecutionEvents('e2', onEvent)
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    await new Promise(r => setTimeout(r, 20))
    expect(onEvent).not.toHaveBeenCalled()
    close()
  })

  it('abort 后 fetch reject 不产生未处理异常', async () => {
    fetchSpy.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            const e = new Error('aborted')
            e.name = 'AbortError'
            reject(e)
          })
        }),
    )
    const close = subscribeExecutionEvents('e3', () => {})
    // 立即关闭——不应抛出 unhandled rejection
    expect(() => close()).not.toThrow()
    await new Promise(r => setTimeout(r, 20))
  })
})

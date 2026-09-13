/**
 * useWorkflowRun：实例化模板 → run/stream 执行 → SSE 点亮 → 取产物。
 * 契约锁定（批次4 打通画布）：
 * 1. 模板节点清单生成步骤骨架（label 用节点自带名，画布侧中文）；
 * 2. node_started/completed/failed 帧映射步骤状态；
 * 3. workflow_completed 后拉 execution 详情取 outputs；
 * 4. 实例化失败等异常诚实回传 error，running 收口。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const instantiateMock = vi.fn()
const requestRunMock = vi.fn()
const getExecutionMock = vi.fn()
vi.mock('@/api/modules/neurflow', () => ({
  instantiateTemplate: (id: string, data: any) => instantiateMock(id, data),
  requestRun: (id: string, inputs: any) => requestRunMock(id, inputs),
  getExecution: (id: string) => getExecutionMock(id),
}))

type FrameHandler = (frame: any) => void
let capturedHandler: FrameHandler | null = null
const subscribeMock = vi.fn((_id: string, onEvent: FrameHandler) => {
  capturedHandler = onEvent
  return () => { capturedHandler = null }
})
vi.mock('@/api/modules/collaboration', () => ({
  subscribeExecutionEvents: (id: string, onEvent: FrameHandler) => subscribeMock(id, onEvent),
}))

import { useWorkflowRun } from '@/composables/useWorkflowRun'

const WORKFLOW = {
  id: 'wf_1',
  nodes: [
    { id: 'script', label: '剧本生成' },
    { id: 'storyboard', label: '分镜拆解' },
    { id: 'compose', label: '成片合成' },
  ],
}

describe('useWorkflowRun', () => {
  beforeEach(() => {
    instantiateMock.mockReset()
    requestRunMock.mockReset()
    getExecutionMock.mockReset()
    subscribeMock.mockClear()
    capturedHandler = null
  })

  it('成功链路：步骤骨架 + 帧点亮 + 产物取出', async () => {
    instantiateMock.mockResolvedValue({ code: 0, data: { workflow: WORKFLOW } })
    requestRunMock.mockResolvedValue({ runId: 'ex_1', status: 'pending', workflow_id: 'wf_1', events_url: '' })
    getExecutionMock.mockResolvedValue({
      execution: { status: 'completed', outputs: { images: [{ url: '/f/a.png' }] }, error: null },
    })

    const { runTemplate, steps, outputs, running } = useWorkflowRun()
    const promise = runTemplate('template_short_drama', '短剧测试', { theme: 'x' })

    await Promise.resolve() // instantiate
    await Promise.resolve() // requestRun
    await vi.waitFor(() => expect(capturedHandler).toBeTruthy())

    capturedHandler!({ type: 'node_started', node_id: 'script', data: {} })
    capturedHandler!({ type: 'node_completed', node_id: 'script', data: {} })
    capturedHandler!({ type: 'workflow_completed', node_id: null, data: {} })

    const outcome = await promise
    expect(outcome.ok).toBe(true)
    expect(outcome.outputs).toEqual({ images: [{ url: '/f/a.png' }] })
    expect(steps.value.find((s) => s.id === 'script')?.status).toBe('success')
    expect(steps.value.find((s) => s.id === 'compose')?.status).toBe('pending')
    expect(steps.value.find((s) => s.id === 'script')?.label).toBe('剧本生成')
    expect(outputs.value).not.toBeNull()
    expect(running.value).toBe(false)
  })

  it('workflow_failed：error 诚实回传', async () => {
    instantiateMock.mockResolvedValue({ workflow: WORKFLOW })
    requestRunMock.mockResolvedValue({ runId: 'ex_2', status: 'pending', workflow_id: 'wf_1', events_url: '' })
    getExecutionMock.mockResolvedValue({ execution: { status: 'failed', outputs: null, error: '上游 401' } })

    const { runTemplate } = useWorkflowRun()
    const promise = runTemplate('t', 'n', {})
    await vi.waitFor(() => expect(capturedHandler).toBeTruthy())
    capturedHandler!({ type: 'node_failed', node_id: 'script', data: {} })
    capturedHandler!({ type: 'workflow_failed', node_id: null, data: { error: '上游 401' } })

    const outcome = await promise
    expect(outcome.ok).toBe(false)
    expect(outcome.error).toContain('401')
  })

  it('实例化失败不抛裸异常，回传 error 且 running 收口', async () => {
    instantiateMock.mockRejectedValue({ response: { data: { detail: '模板不存在' } } })
    const { runTemplate, running, lastError } = useWorkflowRun()
    const outcome = await runTemplate('nope', 'n', {})
    expect(outcome.ok).toBe(false)
    expect(outcome.error).toBe('模板不存在')
    expect(running.value).toBe(false)
    expect(lastError.value).toBe('模板不存在')
  })
})

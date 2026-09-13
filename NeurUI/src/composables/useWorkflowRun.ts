/**
 * 工作流运行 composable（批次4，打通画布与 AIGC 创作页）。
 *
 * 把 CanvasDesignerPage 内联的「SSE 节点事件流 + 轮询兜底 + 完成取结果」逻辑
 * 收敛为可复用内核：实例化内置模板 → run/stream 分离执行（wait=false，后端
 * P0-1 契约）→ 订阅执行事件点亮步骤 → 终态拉取 execution.outputs。
 */
import { ref } from 'vue'
import { getExecution, instantiateTemplate, requestRun } from '@/api/modules/neurflow'
import { subscribeExecutionEvents, type ExecutionEventFrame } from '@/api/modules/collaboration'

export interface RunStep {
  id: string
  label: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'
}

export interface WorkflowRunOutcome {
  ok: boolean
  executionId: string
  status: string
  outputs: Record<string, unknown> | null
  error: string
}

const POLL_INTERVAL_MS = 4000
const MAX_POLL_MS = 20 * 60 * 1000

function unwrap(res: any): any {
  return res?.data ?? res
}

export function useWorkflowRun() {
  const running = ref(false)
  const steps = ref<RunStep[]>([])
  const lastError = ref('')
  const outputs = ref<Record<string, unknown> | null>(null)
  const workflowId = ref('')

  let unsubscribe: (() => void) | null = null

  function cleanup() {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
  }

  function setStep(nodeId: string, status: RunStep['status']) {
    const found = steps.value.find((s) => s.id === nodeId)
    if (found) found.status = status
    else if (nodeId) steps.value.push({ id: nodeId, label: nodeId, status })
  }

  async function fetchOutcome(executionId: string): Promise<WorkflowRunOutcome> {
    const detail = unwrap(await getExecution(executionId))
    const exec = detail?.execution ?? detail
    const status = String(exec?.status || '')
    return {
      ok: status === 'completed' || status === 'success',
      executionId,
      status,
      outputs: exec?.outputs ?? null,
      error: exec?.status === 'failed' ? String(exec?.error || '工作流执行失败') : '',
    }
  }

  /** 轮询兜底（SSE 不可用时）：直到终态或超时 */
  async function pollUntilDone(executionId: string): Promise<WorkflowRunOutcome> {
    const deadline = Date.now() + MAX_POLL_MS
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      const outcome = await fetchOutcome(executionId)
      if (['completed', 'success', 'failed'].includes(outcome.status)) return outcome
    }
    return { ok: false, executionId, status: 'timeout', outputs: null, error: '执行超时（20 分钟）' }
  }

  /**
   * 从模板一键运行。
   * @param templateId 模板 id（如内置 'template_short_drama'）
   * @param name 实例工作流名
   * @param inputs start 节点入参
   */
  async function runTemplate(
    templateId: string,
    name: string,
    inputs: Record<string, unknown>,
  ): Promise<WorkflowRunOutcome> {
    running.value = true
    lastError.value = ''
    outputs.value = null
    steps.value = []
    workflowId.value = ''
    cleanup()

    try {
      // ① 实例化（同时拿节点清单做步骤骨架）
      const instRes = unwrap(await instantiateTemplate(templateId, { name }))
      const workflow = instRes?.workflow
      const wfId: string = workflow?.id || ''
      if (!wfId) throw new Error('模板实例化失败')
      workflowId.value = wfId
      steps.value = (workflow?.nodes || []).map((n: any) => ({
        id: String(n.id),
        label: String(n.label || n.id),
        status: 'pending' as RunStep['status'],
      }))

      // ② run/stream 分离：立即拿 runId + events_url
      const runRes = unwrap(await requestRun(wfId, inputs))
      const executionId: string = runRes?.runId || runRes?.id || ''
      if (!executionId) throw new Error('执行提交失败（未返回 runId）')

      // ③ SSE 驱动点亮；完成/失败终态取 execution 详情
      return await new Promise<WorkflowRunOutcome>((resolve) => {
        let settled = false
        const finish = async (frame?: ExecutionEventFrame) => {
          if (settled) return
          settled = true
          cleanup()
          try {
            const outcome = await fetchOutcome(executionId)
            if (frame?.type === 'workflow_failed') {
              outcome.ok = false
              outcome.error = String((frame.data as any)?.error || outcome.error || '执行失败')
            }
            outputs.value = outcome.outputs
            lastError.value = outcome.ok ? '' : outcome.error
            resolve(outcome)
          } catch (e: any) {
            resolve({ ok: false, executionId, status: 'error', outputs: null, error: String(e?.message || e) })
          } finally {
            running.value = false
          }
        }

        unsubscribe = subscribeExecutionEvents(executionId, (frame) => {
          if (frame.node_id && frame.type.startsWith('node_')) {
            const map: Record<string, RunStep['status']> = {
              node_started: 'running',
              node_completed: 'success',
              node_failed: 'failed',
              node_skipped: 'skipped',
            }
            setStep(frame.node_id, map[frame.type] || 'running')
          }
          if (frame.type === 'workflow_completed' || frame.type === 'workflow_failed') {
            void finish(frame)
          }
        })

        // SSE 建连失败兜底：轮询执行状态
        void pollUntilDone(executionId).then((outcome) => {
          if (settled) return
          if (outcome.ok || outcome.error) finish()
        })
      })
    } catch (e: any) {
      running.value = false
      lastError.value = String(e?.response?.data?.detail || e?.message || e)
      return { ok: false, executionId: '', status: 'error', outputs: null, error: lastError.value }
    }
  }

  return { running, steps, lastError, outputs, workflowId, runTemplate, cleanup }
}

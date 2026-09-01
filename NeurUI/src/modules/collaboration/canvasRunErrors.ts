/**
 * canvasRunErrors — 节点异常弹窗数据格式化（纯函数）。
 *
 * extractRunBlockDetail：axios 错误 → 后端 400 节点清单结构；
 * collectFailedNodes：轮询 node_results → failed 节点列表。
 */

export interface NodeConfigIssueView {
  label: string
  message: string
  missing?: string[]
}

export interface FailedNodeView {
  nodeId: string
  error?: string | null
}

export interface RunBlockDetail {
  message: string
  issues: NodeConfigIssueView[]
}

export function extractRunBlockDetail(err: any): RunBlockDetail | null {
  const detail = err?.response?.data?.detail
  if (!detail || typeof detail !== 'object') return null
  if (detail.code !== 1 || !Array.isArray(detail.errors)) return null
  return {
    message: String(detail.message ?? '节点配置异常，已停止执行'),
    issues: detail.errors.map((e: any) => ({
      label: e.label ?? e.node_id ?? '',
      message: e.message ?? '',
      missing: Array.isArray(e.missing) ? e.missing : undefined,
    })),
  }
}

export function collectFailedNodes(
  nodeResults: Record<string, { status: string; error?: string | null }>,
): FailedNodeView[] {
  return Object.entries(nodeResults ?? {})
    .filter(([, r]) => r?.status === 'failed')
    .map(([nodeId, r]) => ({ nodeId, error: r.error }))
}

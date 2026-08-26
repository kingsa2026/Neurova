import type { WorkflowDefinition } from '@/api/modules/neurflow'

/**
 * 从各种响应形状中安全提取工作流列表。
 *
 * 后端 GET /neurflow/workflows 返回 { workflows: [...], total }，
 * 经 api 客户端包装后为 { code, data: { workflows, total } }；
 * 兼容裸数组与 { data: [...] }，无法识别时返回空数组（不抛错）。
 */
export function extractWorkflowList(res: unknown): WorkflowDefinition[] {
  const unwrap = (value: unknown): unknown => {
    if (value && typeof value === 'object' && 'data' in (value as Record<string, unknown>)) {
      return (value as Record<string, unknown>).data
    }
    return value
  }

  let cur = unwrap(res)
  if (Array.isArray(cur)) return cur as WorkflowDefinition[]

  if (cur && typeof cur === 'object') {
    const obj = cur as Record<string, unknown>
    if (Array.isArray(obj.workflows)) return obj.workflows as WorkflowDefinition[]
    cur = unwrap(obj)
    if (Array.isArray(cur)) return cur as WorkflowDefinition[]
  }

  return []
}

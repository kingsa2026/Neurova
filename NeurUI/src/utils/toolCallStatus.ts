/**
 * 工具执行状态判定（补课 F：Offload 横幅）。
 *
 * 后端 ToolCoordinator 超时转后台后，tool_result 的 result 内容为
 * {"status":"background","task_id":...} 信封（tool_executor.py:677 返回
 * core_out 原样，_safe_json_dumps 后透传 SSE）。前端据此渲染
 * "后台运行中" 徽章与提示，不与"失败"混淆。
 */
export function isBackgroundResult(result?: string | null): boolean {
  if (!result) return false
  const text = String(result)
  // 快速路径：JSON 解析 status 字段
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>
    return parsed?.status === 'background'
  } catch {
    // 非 JSON（含转义/截断）：子串兜底
  }
  return text.includes('"status":"background"') || text.includes('"status": "background"')
}

/** 运行中（有 tool_call 无 result）。 */
export function isRunningTool(result?: string | null): boolean {
  return result === undefined || result === null
}

/**
 * 工具失败判定（工具调用链升级 T7：聊天时间轴失败徽标对齐）。
 *
 * 后端 role=tool 失败信封形态（loops/base.py 失败回传 + 升级计划 T2/T5）：
 * - {"error": "..."}                  —— 文本通道/兜底失败
 * - {"success": false, "error": "...", "param_errors": [...]}   —— T2 参数校验拒绝
 * - {"success": false, "error": "...", "validation": {...}}     —— T5 落地校验拒绝
 * 判据与后端 _result_is_success 同构（success===false 或 error 非空字符串）；
 * background 信封非失败。非 JSON/无法判定 → false（保守不扩大红色面）。
 */
export function isToolFailureResult(result?: string | null): boolean {
  if (!result) return false
  const text = String(result)
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return false
    if (parsed.status === 'background') return false
    if (parsed.success === false) return true
    return typeof parsed.error === 'string' && parsed.error.length > 0
  } catch {
    // 非 JSON 结果（纯文本工具输出）无法判定成败，维持"有结果即完成"
    return false
  }
}

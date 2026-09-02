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

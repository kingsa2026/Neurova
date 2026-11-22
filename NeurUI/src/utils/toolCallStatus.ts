/**
 * 工具执行状态判定（补课 F：Offload 横幅）。
 *
 * 后端 ToolCoordinator 超时转后台后，tool_result 的 result 内容为
 * {"status":"background","task_id":...} 信封（tool_executor.py:677 返回
 * core_out 原样，_safe_json_dumps 后透传 SSE）。前端据此渲染
 * "后台运行中" 徽章与提示，不与"失败"混淆。
 */
import i18n from '@/i18n'

/** 已知 error_code 的专用提示键（其余走 phase/通用映射） */
const ERROR_CODE_HINT_KEYS: Record<string, string> = {
  HOST_KEY_MISMATCH: 'chat.failHostKeyMismatch',
  TOOL_UNSUPPORTED: 'chat.failUnsupported',
}

/**
 * E1/E3/E4：结构化失败载荷 → 一行可读提示。
 *
 * /tools/execute 失败响应 data.result 携带 error_code/phase/retryable/
 * executed/param_errors/pending_approval（45a8c452c 起透传），此前前端只显示
 * 裸 error 串。本函数把可判读语义映射为本地化提示；非 JSON/成功结果/
 * 无结构化字段 → 空串（回退原有裸 error 展示，存量载荷行为不变）。
 */
export function toolFailureHint(result?: string | null): string {
  if (!result) return ''
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(String(result)) as Record<string, unknown>
  } catch {
    return ''
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return ''
  if (parsed.success !== false && parsed.pending_approval !== true && !parsed.error) return ''
  const t = i18n.global.t
  const parts: string[] = []
  if (parsed.pending_approval === true) parts.push(t('chat.failPendingApproval'))
  const code = typeof parsed.error_code === 'string' ? parsed.error_code : ''
  const phase = typeof parsed.phase === 'string' ? parsed.phase : ''
  const knownCode = ERROR_CODE_HINT_KEYS[code]
  if (knownCode) {
    parts.push(t(knownCode))
  } else if (code === 'REMOTE_NOT_EXECUTED') {
    if (phase === 'auth') parts.push(t('chat.failAuthFailed'))
    else if (phase === 'connect' || phase === 'timeout') parts.push(t('chat.failHostUnreachable'))
    else parts.push(t('chat.failRemoteFailed'))
  } else if (code) {
    parts.push(t('chat.failErrorCode', { code }))
  }
  if (parsed.executed === false) parts.push(t('chat.failNotExecuted'))
  if (parsed.retryable === true) parts.push(t('chat.failRetryable'))
  else if (parsed.executed === 'unknown') parts.push(t('chat.failNoRetry'))
  if (Array.isArray(parsed.param_errors) && parsed.param_errors.length > 0) {
    parts.push(t('chat.failParamErrors', { errors: parsed.param_errors.map(String).join('; ') }))
  }
  return parts.join(' · ')
}

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

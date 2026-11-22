/**
 * toolFailureHint：结构化失败载荷 → 可读提示（E1/E3/E4）。
 *
 * /tools/execute 失败响应 data.result 携带 error_code/phase/retryable/
 * executed/param_errors/pending_approval；此前前端只显示裸 error 串。
 * 验收：pending_approval/主机不可达/认证失败/指纹变化/参数错误各映射到
 * 对应提示；executed=false 与 retryable 语义分档；非 JSON/成功结果 → 空串。
 */
import { describe, it, expect } from 'vitest'
import { toolFailureHint } from '../toolCallStatus'

describe('toolFailureHint', () => {
  it('pending_approval → 待人工确认', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, pending_approval: true, error: '需要审批',
    }))
    expect(hint).toContain('待人工确认')
  })

  it('REMOTE_NOT_EXECUTED phase=connect → 主机不可达、未执行、可重试', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'REMOTE_NOT_EXECUTED', phase: 'connect',
      retryable: true, executed: false, error: 'SSH 连接失败',
    }))
    expect(hint).toContain('不可达')
    expect(hint).toContain('未在远端执行')
    expect(hint).toContain('可安全重试')
  })

  it('REMOTE_NOT_EXECUTED phase=auth → 认证失败', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'REMOTE_NOT_EXECUTED', phase: 'auth',
      retryable: true, executed: false, error: 'SSH 认证失败',
    }))
    expect(hint).toContain('认证失败')
  })

  it('HOST_KEY_MISMATCH → 指纹不一致拒连', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'HOST_KEY_MISMATCH', error: 'fingerprint mismatch',
    }))
    expect(hint).toContain('不一致')
  })

  it('TOOL_UNSUPPORTED → 不受支持', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'TOOL_UNSUPPORTED', error: 'unsupported',
    }))
    expect(hint).toContain('不受支持')
  })

  it('未知 error_code → 点名错误码', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'SOMETHING_ELSE', error: 'x',
    }))
    expect(hint).toContain('SOMETHING_ELSE')
  })

  it('executed=unknown → 不宜盲目重试', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error_code: 'REMOTE_NOT_EXECUTED', phase: 'exec',
      retryable: false, executed: 'unknown', error: '部分输出已获取',
    }))
    expect(hint).toContain('不宜盲目重试')
    expect(hint).not.toContain('可安全重试')
  })

  it('param_errors 列表拼入提示', () => {
    const hint = toolFailureHint(JSON.stringify({
      success: false, error: '参数校验失败',
      param_errors: ['host 不能为空', 'command 不能为空'],
    }))
    expect(hint).toContain('host 不能为空; command 不能为空')
  })

  it('非 JSON / 成功结果 / 无结构化字段 → 空串（回退裸 error 展示）', () => {
    expect(toolFailureHint('plain text output')).toBe('')
    expect(toolFailureHint(JSON.stringify({ success: true, stdout: 'ok' }))).toBe('')
    expect(toolFailureHint(JSON.stringify({ success: false, error: '裸错误' }))).toBe('')
    expect(toolFailureHint(null)).toBe('')
    expect(toolFailureHint(undefined)).toBe('')
  })
})

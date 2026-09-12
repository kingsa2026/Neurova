import { describe, expect, it } from 'vitest'
import { isBackgroundResult, isRunningTool, isToolFailureResult } from '@/utils/toolCallStatus'

describe('isBackgroundResult', () => {
  it('detects JSON background envelope', () => {
    expect(isBackgroundResult('{"status":"background","task_id":"t1"}')).toBe(true)
  })
  it('detects with spaces', () => {
    expect(isBackgroundResult('{"status": "background"}')).toBe(true)
  })
  it('rejects success / error results', () => {
    expect(isBackgroundResult('{"status":"completed","data":1}')).toBe(false)
    expect(isBackgroundResult('{"error":"boom"}')).toBe(false)
  })
  it('rejects empty / null', () => {
    expect(isBackgroundResult('')).toBe(false)
    expect(isBackgroundResult(null)).toBe(false)
    expect(isBackgroundResult(undefined)).toBe(false)
  })
})

describe('isRunningTool', () => {
  it('no result = running', () => {
    expect(isRunningTool(undefined)).toBe(true)
    expect(isRunningTool(null)).toBe(true)
  })
  it('any result = done', () => {
    expect(isRunningTool('x')).toBe(false)
  })
})

describe('isToolFailureResult', () => {
  it('detects T2 param_errors envelope', () => {
    expect(
      isToolFailureResult(
        '{"success": false, "error": "参数校验未通过: limit: ...", "param_errors": ["limit: ..."]}'
      )
    ).toBe(true)
  })
  it('detects T5 ungrounded envelope', () => {
    expect(
      isToolFailureResult('{"success": false, "error": "参数落地校验未通过: ...", "validation": {"ungrounded": ["date: ..."]}}')
    ).toBe(true)
  })
  it('detects legacy error-only envelope', () => {
    expect(isToolFailureResult('{"error": "boom"}')).toBe(true)
  })
  it('rejects successful results', () => {
    expect(isToolFailureResult('{"success": true, "data": 1}')).toBe(false)
    expect(isToolFailureResult('{"city": "北京", "temp_c": 27}')).toBe(false)
    expect(isToolFailureResult('{"error": null}')).toBe(false)
    expect(isToolFailureResult('{"error": ""}')).toBe(false)
  })
  it('background envelope is not failure', () => {
    expect(isToolFailureResult('{"status":"background","task_id":"t1"}')).toBe(false)
  })
  it('empty / non-JSON cannot judge → not failure', () => {
    expect(isToolFailureResult('')).toBe(false)
    expect(isToolFailureResult(null)).toBe(false)
    expect(isToolFailureResult(undefined)).toBe(false)
    expect(isToolFailureResult('plain text result')).toBe(false)
  })
})

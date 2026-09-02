import { describe, expect, it } from 'vitest'
import { isBackgroundResult, isRunningTool } from '@/utils/toolCallStatus'

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

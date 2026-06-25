/**
 * 阶段6 RED: 验证统一错误处理库
 *
 * 测试内容：
 * 1. AppError 类可实例化，包含 message/code/severity/context 属性
 * 2. handleError(error) 将普通 Error 转为 AppError
 * 3. handleError(appError) 保留原有 AppError
 * 4. handleError 调用 logger.error 并触发 bus.emit
 * 5. withErrorBoundary(fn) 包装函数，捕获异常并处理
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { AppError, handleError, withErrorBoundary } from '../error'
import logger from '../logger'
import bus from '@/bus'

describe('AppError - 实例化', () => {
  it('应可使用 message 实例化', () => {
    const err = new AppError('出错了')
    expect(err).toBeInstanceOf(Error)
    expect(err).toBeInstanceOf(AppError)
    expect(err.message).toBe('出错了')
  })

  it('应支持自定义 code', () => {
    const err = new AppError('未找到', 'NOT_FOUND')
    expect(err.code).toBe('NOT_FOUND')
  })

  it('应支持自定义 severity', () => {
    const err = new AppError('严重错误', 'FATAL', 'high')
    expect(err.severity).toBe('high')
  })

  it('应支持自定义 context', () => {
    const err = new AppError('错误', 'ERR', 'medium', { userId: 123, action: 'login' })
    expect(err.context).toEqual({ userId: 123, action: 'login' })
  })

  it('默认 code 应为 UNKNOWN', () => {
    const err = new AppError('错误')
    expect(err.code).toBe('UNKNOWN')
  })

  it('默认 severity 应为 medium', () => {
    const err = new AppError('错误')
    expect(err.severity).toBe('medium')
  })

  it('name 应为 AppError', () => {
    const err = new AppError('错误')
    expect(err.name).toBe('AppError')
  })
})

describe('handleError - 转换普通 Error', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('应将普通 Error 转为 AppError', () => {
    const original = new Error('原始错误')
    const result = handleError(original)
    expect(result).toBeInstanceOf(AppError)
    expect(result.message).toBe('原始错误')
    expect(result.code).toBe('UNEXPECTED')
  })

  it('应将字符串错误转为 AppError', () => {
    const result = handleError('字符串错误')
    expect(result).toBeInstanceOf(AppError)
    expect(result.message).toBe('字符串错误')
  })

  it('应将未知类型转为 AppError', () => {
    const result = handleError({ weird: 'object' })
    expect(result).toBeInstanceOf(AppError)
    expect(typeof result.message).toBe('string')
  })

  it('应保留 context 参数', () => {
    const result = handleError(new Error('err'), 'UserService.login')
    expect(result.context).toEqual({ context: 'UserService.login' })
  })
})

describe('handleError - 保留 AppError', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('传入 AppError 应保留原对象引用', () => {
    const appError = new AppError('业务错误', 'BIZ_ERROR', 'high', { foo: 'bar' })
    const result = handleError(appError)
    expect(result).toBe(appError)
    expect(result.code).toBe('BIZ_ERROR')
    expect(result.severity).toBe('high')
    expect(result.context).toEqual({ foo: 'bar' })
  })
})

describe('handleError - logger 与 bus 集成', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('handleError 应调用 logger.error', () => {
    handleError(new Error('测试错误'))
    const logs = logger.getLogs()
    expect(logs.some((l) => l.level === 'error')).toBe(true)
  })

  it('handleError 应触发 bus notification:show 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    handleError(new Error('通知错误'))
    expect(handler).toHaveBeenCalled()
    // 至少有一次携带 type=error 和 message
    const calls = handler.mock.calls
    const hasErrorCall = calls.some(
      (call) => call[0]?.type === 'error' && call[0]?.message === '通知错误',
    )
    expect(hasErrorCall).toBe(true)
    bus.off('notification:show', handler)
  })

  it('handleError 应返回 AppError 实例', () => {
    const result = handleError(new Error('err'))
    expect(result).toBeInstanceOf(AppError)
  })
})

describe('withErrorBoundary - 函数包装', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('包装的函数正常执行时应返回结果', () => {
    const fn = (a: number, b: number) => a + b
    const wrapped = withErrorBoundary(fn)
    expect(wrapped(1, 2)).toBe(3)
  })

  it('包装的函数抛出异常时应被捕获并处理', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    const fn = () => {
      throw new Error('函数错误')
    }
    const wrapped = withErrorBoundary(fn)
    expect(() => wrapped()).toThrow('函数错误')
    // 应触发 bus 事件
    expect(handler).toHaveBeenCalled()
    bus.off('notification:show', handler)
  })

  it('应透传参数给原函数', () => {
    const fn = vi.fn((a: number, b: number) => a * b)
    const wrapped = withErrorBoundary(fn)
    wrapped(3, 4)
    expect(fn).toHaveBeenCalledWith(3, 4)
  })

  it('应支持 context 参数', () => {
    const fn = () => {
      throw new Error('ctx 错误')
    }
    const wrapped = withErrorBoundary(fn, 'MyModule.myFunc')
    try {
      wrapped()
    } catch {
      // 忽略
    }
    const logs = logger.getLogs()
    expect(logs.length).toBeGreaterThan(0)
  })
})

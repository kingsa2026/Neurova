/**
 * 统一错误处理库 - 错误归一化与边界保护
 *
 * 所有 UI 错误必须通过此库处理，禁止直接 throw/catch 后静默。
 *
 * 特性：
 * - AppError 统一错误类型（message/code/severity/context）
 * - handleError 将任意异常归一为 AppError，并联动 logger + bus
 * - withErrorBoundary 包装函数，自动捕获异常并处理
 *
 * 用法：
 *   import { AppError, handleError, withErrorBoundary } from '@/utils/error'
 *   throw new AppError('未找到', 'NOT_FOUND', 'high', { id: 1 })
 *   handleError(err)
 *   const safe = withErrorBoundary(riskyFn, 'Module.action')
 */
import bus from '@/bus'
import logger from './logger'

export type ErrorSeverity = 'low' | 'medium' | 'high'

export class AppError extends Error {
  constructor(
    message: string,
    public code: string = 'UNKNOWN',
    public severity: ErrorSeverity = 'medium',
    public context?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'AppError'
  }
}

/**
 * 将任意错误归一化为 AppError：
 * - 已是 AppError：原样返回（保留 code/severity/context）
 * - Error 实例：包装为 UNEXPECTED
 * - 其他类型：String() 转换后包装
 *
 * 同时联动 logger.error 记录日志，并触发 bus notification:show 事件。
 *
 * @param error 任意异常
 * @param context 可选的调用上下文标识（如 "UserService.login"）
 * @returns 归一化后的 AppError
 */
export function handleError(error: unknown, context?: string): AppError {
  const appError =
    error instanceof AppError
      ? error
      : new AppError(
          error instanceof Error ? error.message : String(error),
          'UNEXPECTED',
          'medium',
          { context },
        )

  logger.error(`[${appError.code}] ${appError.message}`, {
    context,
    stack: appError.stack,
  })
  bus.emit('notification:show', { type: 'error', message: appError.message })
  return appError
}

/**
 * 函数错误边界包装器：
 * - 正常执行：返回原函数结果
 * - 抛出异常：调用 handleError 处理后重新抛出（保留调用栈）
 *
 * @param fn 被包装的函数
 * @param context 可选的调用上下文标识
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function withErrorBoundary<T extends (...args: any[]) => any>(
  fn: T,
  context?: string,
): T {
  return ((...args: Parameters<T>) => {
    try {
      return fn(...args)
    } catch (error) {
      handleError(error, context)
      throw error
    }
  }) as T
}

export default { AppError, handleError, withErrorBoundary }

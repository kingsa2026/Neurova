/**
 * 统一前端日志库 - 收集与分发日志
 *
 * 所有 UI 日志必须通过此库记录，禁止直接调用 console。
 *
 * 特性：
 * - 四级日志：debug/info/warn/error
 * - 级别过滤（setLevel 控制输出阈值）
 * - 内存收集最近 100 条日志（getLogs 返回副本）
 * - 与事件总线集成（error 级别触发 notification:show 事件）
 *
 * 用法：
 *   import logger from '@/utils/logger'
 *   logger.info('信息')
 *   logger.error('出错了', { code: 500 })
 *   const logs = logger.getLogs()
 */
import bus from '@/bus'

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
}

export interface LogEntry {
  level: LogLevel
  message: string
  timestamp: number
  args?: unknown[]
}

class FrontendLogger {
  private level: LogLevel = import.meta.env.DEV ? 'debug' : 'info'
  private logs: LogEntry[] = []
  private maxLogs = 100

  /**
   * 设置当前日志级别，低于此级别的日志将被丢弃
   */
  setLevel(level: LogLevel): void {
    this.level = level
  }

  debug(message: string, ...args: unknown[]): void {
    this.log('debug', message, args)
  }

  info(message: string, ...args: unknown[]): void {
    this.log('info', message, args)
  }

  warn(message: string, ...args: unknown[]): void {
    this.log('warn', message, args)
  }

  error(message: string, ...args: unknown[]): void {
    this.log('error', message, args)
    // error 级别同步触发通知事件，便于 UI 层统一提示
    bus.emit('notification:show', { type: 'error', message })
  }

  private log(level: LogLevel, message: string, args: unknown[]): void {
    // 级别过滤：低于当前级别的日志直接丢弃
    if (LOG_LEVELS[level] < LOG_LEVELS[this.level]) return

    const timestamp = Date.now()
    this.logs.push({ level, message, timestamp, args })

    // 超过容量时丢弃最旧日志（FIFO）
    if (this.logs.length > this.maxLogs) {
      this.logs.shift()
    }

    // 同步输出到 console，便于开发调试
    const fn = console[level] || console.log
    fn(`[${level.toUpperCase()}] ${message}`, ...args)
  }

  /**
   * 返回已收集日志的深拷贝副本，外部修改不影响内部状态
   * （数组与每个 LogEntry 都是新对象）
   */
  getLogs(): LogEntry[] {
    return this.logs.map((entry) => ({ ...entry }))
  }

  /**
   * 清空已收集的日志
   */
  clear(): void {
    this.logs = []
  }
}

export const logger = new FrontendLogger()
export default logger

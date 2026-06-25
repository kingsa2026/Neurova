/**
 * Logger - 统一日志库
 *
 * 职责：统一管理应用所有日志输出
 * 设计：单例模式，支持级别过滤、历史记录、hilog 集成
 *
 * 用法：
 *   const logger = Logger.getInstance();
 *   logger.info('Tag', 'message');
 */

import { hilog } from '@kit.PerformanceAnalysisKit';

/** 日志级别 */
export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
  FATAL = 4,
}

/** 日志条目 */
export interface LogEntry {
  level: LogLevel;
  tag: string;
  message: string;
  timestamp: number;
  error?: Error;
}

const DOMAIN = 0x0001;
const MAX_HISTORY = 500;

export class Logger {
  private static instance: Logger;
  private level: LogLevel = LogLevel.DEBUG;
  private history: LogEntry[] = [];

  private constructor() {}

  static getInstance(): Logger {
    if (!Logger.instance) {
      Logger.instance = new Logger();
    }
    return Logger.instance;
  }

  /** 设置日志级别 */
  setLevel(level: LogLevel): void {
    this.level = level;
  }

  /** 获取当前日志级别 */
  getLevel(): LogLevel {
    return this.level;
  }

  /** DEBUG 级别日志 */
  debug(tag: string, message: string, ...args: Object[]): void {
    this.log(LogLevel.DEBUG, tag, message, undefined, args);
  }

  /** INFO 级别日志 */
  info(tag: string, message: string, ...args: Object[]): void {
    this.log(LogLevel.INFO, tag, message, undefined, args);
  }

  /** WARN 级别日志 */
  warn(tag: string, message: string, ...args: Object[]): void {
    this.log(LogLevel.WARN, tag, message, undefined, args);
  }

  /** ERROR 级别日志 */
  error(tag: string, message: string, error?: Error, ...args: Object[]): void {
    this.log(LogLevel.ERROR, tag, message, error, args);
  }

  /** FATAL 级别日志 */
  fatal(tag: string, message: string, error?: Error, ...args: Object[]): void {
    this.log(LogLevel.FATAL, tag, message, error, args);
  }

  /** 内部日志方法 */
  private log(
    level: LogLevel,
    tag: string,
    message: string,
    error?: Error,
    args?: Object[]
  ): void {
    // 级别过滤
    if (level < this.level) {
      return;
    }

    const entry: LogEntry = {
      level,
      tag,
      message: args && args.length > 0 ? `${message} ${JSON.stringify(args)}` : message,
      timestamp: Date.now(),
      error,
    };

    // 写入历史
    this.history.push(entry);
    if (this.history.length > MAX_HISTORY) {
      this.history.shift();
    }

    // 输出到 hilog
    const levelName = LogLevel[level];
    if (level >= LogLevel.ERROR) {
      hilog.error(DOMAIN, tag, '[%{public}s] %{public}s', levelName, entry.message);
    } else if (level >= LogLevel.WARN) {
      hilog.warn(DOMAIN, tag, '[%{public}s] %{public}s', levelName, entry.message);
    } else {
      hilog.info(DOMAIN, tag, '[%{public}s] %{public}s', levelName, entry.message);
    }
  }

  /** 获取历史日志（测试用） */
  getHistory(): LogEntry[] {
    return this.history;
  }

  /** 清空历史（测试用） */
  clearHistory(): void {
    this.history = [];
  }
}

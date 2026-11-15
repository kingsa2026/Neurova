/**
 * ErrorManager - 统一错误库
 *
 * 职责：统一管理应用所有错误的创建、上报、分发、历史记录
 * 设计：单例模式，支持错误码处理器注册、HTTP 状态映射、原生 Error 转换
 *
 * 用法：
 *   const em = ErrorManager.getInstance();
 *   const err = em.create('auth_failed', '认证失败', ErrorCategory.AUTH);
 *   em.report(err);
 *   em.registerHandler('auth_failed', (e) => { /* 处理 *\/ });
 */

import { Logger } from '../logger/Logger';

/** 错误分类 */
export enum ErrorCategory {
  NETWORK = 'network',
  AUTH = 'auth',
  API = 'api',
  WEBSOCKET = 'websocket',
  STORAGE = 'storage',
  UI = 'ui',
  BUSINESS = 'business',
  UNKNOWN = 'unknown',
}

/** 应用错误对象 */
export interface AppError {
  code: string;            // 错误码字符串
  message: string;         // 用户可见消息
  category: ErrorCategory; // 错误分类
  timestamp: number;       // 发生时间戳（毫秒）
  details?: Object;        // 可选额外上下文
  cause?: Error;           // 可选原始错误
}

/** 错误处理器函数 */
export type ErrorHandler = (error: AppError) => void;

/** HTTP 状态码 → 错误分类映射 */
function mapHttpStatusToCategory(status: number): ErrorCategory {
  if (status === 0) return ErrorCategory.NETWORK;
  if (status === 401 || status === 403) return ErrorCategory.AUTH;
  if (status >= 400 && status < 600) return ErrorCategory.API;
  return ErrorCategory.UNKNOWN;
}

export class ErrorManager {
  private static instance: ErrorManager;
  private history: AppError[] = [];
  private handlers: Map<string, ErrorHandler> = new Map();
  private maxHistory: number = 100;
  private logger: Logger = Logger.getInstance();

  private constructor() {}

  static getInstance(): ErrorManager {
    if (!ErrorManager.instance) {
      ErrorManager.instance = new ErrorManager();
    }
    return ErrorManager.instance;
  }

  /** 创建 AppError（不自动上报） */
  create(
    code: string,
    message: string,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    details?: Object,
  ): AppError {
    const err: AppError = {
      code,
      message,
      category,
      timestamp: Date.now(),
    };
    if (details !== undefined) {
      err.details = details;
    }
    return err;
  }

  /** 上报错误：记录历史 + 触发已注册处理器 */
  report(error: AppError): void {
    // 记录历史
    this.history.push(error);
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }

    // 日志输出
    this.logger.error('ErrorManager', `[${error.category}] ${error.code}: ${error.message}`);

    // 触发处理器
    const handler = this.handlers.get(error.code);
    if (handler) {
      try {
        handler(error);
      } catch (e) {
        this.logger.error('ErrorManager', '处理器执行失败', e as Error);
      }
    }
  }

  /** 便捷方法：创建并上报一步完成 */
  reportError(
    code: string,
    message: string,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    details?: Object,
  ): AppError {
    const err = this.create(code, message, category, details);
    this.report(err);
    return err;
  }

  /** 获取错误历史（只读副本） */
  getHistory(): AppError[] {
    return this.history.slice();
  }

  /** 清空历史 */
  clearHistory(): void {
    this.history = [];
  }

  /** 注册错误码处理器 */
  registerHandler(code: string, handler: ErrorHandler): void {
    this.handlers.set(code, handler);
  }

  /** 注销错误码处理器 */
  unregisterHandler(code: string): void {
    this.handlers.delete(code);
  }

  /** 清空所有处理器 */
  clearHandlers(): void {
    this.handlers.clear();
  }

  /** 从 HTTP 状态码创建错误 */
  fromHttpStatus(status: number, message?: string): AppError {
    const category = mapHttpStatusToCategory(status);
    const code = `http_${status}`;
    const msg = message || `HTTP ${status} 错误`;
    return this.create(code, msg, category);
  }

  /** 从原生 Error 转换 */
  fromError(err: Error, category: ErrorCategory = ErrorCategory.UNKNOWN): AppError {
    const appErr = this.create('native_error', err.message, category);
    appErr.cause = err;
    return appErr;
  }
}

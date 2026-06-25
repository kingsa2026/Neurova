/**
 * HttpAdapter - HTTP 适配层
 *
 * 职责：桥接 HttpClient 与鸿蒙 @kit.NetworkKit http 模块，将上层统一 HTTP 调用
 *      转译为鸿蒙系统 HTTP API；最小封装，不含业务逻辑
 * 设计：单例模式，实现 HttpBackend 接口；由 install() 注入 HttpClient 后端
 *
 * 用法：
 *   HttpAdapter.getInstance().install();   // 应用启动时一次性注入
 *   // 之后所有 HttpClient 请求自动走鸿蒙 http
 */

import { http } from '@kit.NetworkKit';
import { Logger } from '../logger/Logger';
import { ConfigManager } from '../config/ConfigManager';
import { HttpClient, HttpBackend } from '../api/HttpClient';
import { ApiResponse } from '../types';

export class HttpAdapter implements HttpBackend {
  private static instance: HttpAdapter;
  private logger: Logger = Logger.getInstance();
  private config: ConfigManager = ConfigManager.getInstance();

  /** 默认请求头（调用方传入的同名头会覆盖此处） */
  private readonly defaultHeaders: Record<string, string> = {
    'Accept': 'application/json',
    'User-Agent': 'NeurovaHarmony/1.0',
  };

  private constructor() {}

  /** 获取单例实例 */
  static getInstance(): HttpAdapter {
    if (!HttpAdapter.instance) {
      HttpAdapter.instance = new HttpAdapter();
    }
    return HttpAdapter.instance;
  }

  /** 注入 HttpClient：将自身设为后端，之后 HttpClient 所有请求经本适配层发出 */
  install(): void {
    HttpClient.getInstance().setBackend(this);
    this.logger.info('HttpAdapter', '已注入 HttpClient');
  }

  /** 核心请求方法：实现 HttpBackend 接口 */
  async request(
    method: string,
    url: string,
    body: Object | null,
    headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    // 创建鸿蒙 HTTP 请求对象
    const httpRequest = http.createHttp();

    // 从配置读取超时时间（默认 15000ms）
    const timeout: number = this.config.get<number>('request_timeout', 15000);

    try {
      // 合并请求头：默认头 + 调用方传入的头（后者覆盖前者）
      const mergedHeaders: Record<string, string> = {
        ...this.defaultHeaders,
        ...headers,
      };

      // 构建鸿蒙请求选项
      const options: http.HttpRequestOptions = {
        method: this.toHttpMethod(method),
        header: mergedHeaders,
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: timeout,
        readTimeout: timeout,
      };

      // 非 null body 序列化为 JSON 字符串（GET/DELETE 传 null 不带 body）
      if (body !== null) {
        options.extraData = JSON.stringify(body);
      }

      this.logger.debug('HttpAdapter', `${method} ${url}`);

      // 发起请求
      const response = await httpRequest.request(url, options);
      const status: number = response.responseCode;

      // 解析响应体为 ApiResponse
      const data = this.parseResponseBody(response.result);

      return { status, data };
    } catch (e) {
      const err = e as Error;
      this.logger.error('HttpAdapter', `${method} ${url} 请求失败`, err);
      // 抛出包含 url 和 method 信息的错误，便于上层定位
      throw new Error(`[HttpAdapter] ${method} ${url} 网络请求失败: ${err.message}`);
    } finally {
      // 无论成功失败，销毁请求对象释放系统资源
      httpRequest.destroy();
    }
  }

  /** 将字符串方法名转为鸿蒙 http.HttpRequestMethod 枚举 */
  private toHttpMethod(method: string): http.HttpRequestMethod {
    const upper = method.toUpperCase();
    switch (upper) {
      case 'GET':
        return http.HttpRequestMethod.GET;
      case 'POST':
        return http.HttpRequestMethod.POST;
      case 'PUT':
        return http.HttpRequestMethod.PUT;
      case 'DELETE':
        return http.HttpRequestMethod.DELETE;
      case 'HEAD':
        return http.HttpRequestMethod.HEAD;
      case 'OPTIONS':
        return http.HttpRequestMethod.OPTIONS;
      case 'TRACE':
        return http.HttpRequestMethod.TRACE;
      case 'CONNECT':
        return http.HttpRequestMethod.CONNECT;
      default:
        this.logger.warn('HttpAdapter', `未知 HTTP 方法 ${method}，降级为 GET`);
        return http.HttpRequestMethod.GET;
    }
  }

  /** 解析响应体为 ApiResponse<Object>，兼容字符串/对象/空值 */
  private parseResponseBody(raw: Object): ApiResponse<Object> {
    // 字符串：尝试 JSON.parse
    if (typeof raw === 'string') {
      const text = raw as string;
      if (text.length === 0) {
        return { code: 0, message: '空响应体', data: {} as Object };
      }
      try {
        return JSON.parse(text) as ApiResponse<Object>;
      } catch (e) {
        // 非 JSON 响应：包装为标准 ApiResponse，原文本放入 data
        this.logger.warn('HttpAdapter', `响应非 JSON 格式: ${text.slice(0, 200)}`);
        return {
          code: -1,
          message: '响应体非 JSON 格式',
          data: text as Object,
        };
      }
    }

    // 已是对象（理论上 expectDataType=STRING 不会出现，做防御性处理）
    if (raw !== null && typeof raw === 'object') {
      return raw as ApiResponse<Object>;
    }

    // 其他类型（ArrayBuffer 等）：包装返回
    return {
      code: -1,
      message: '不支持的响应体类型',
      data: {} as Object,
    };
  }
}

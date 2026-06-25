/**
 * HttpClient - 统一 HTTP 客户端
 *
 * 职责：统一管理应用所有 HTTP 请求（GET/POST/PUT/DELETE/Upload）
 * 设计：单例模式，可注入 HttpBackend 便于测试，自动 token 注入、X-Request-ID、错误分发
 *
 * 用法：
 *   const client = HttpClient.getInstance();
 *   client.setBaseUrl('https://api.example.com');
 *   client.setToken('jwt-xxx');
 *   const res = await client.get('/users/me');
 */

import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';
import { ErrorManager, ErrorCategory, AppError } from '../error/ErrorManager';
import { ApiResponse } from '../types';

/** HTTP 后端接口（生产用 @ohos.net.http 实现，测试用 mock） */
export interface HttpBackend {
  request(
    method: string,
    url: string,
    body: Object | null,
    headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }>;
}

/** 拦截器接口 */
export interface HttpInterceptor {
  before?(headers: Record<string, string>): void;
  after?(response: { status: number; data: ApiResponse<Object> }): void;
}

/** 请求配置 */
export interface RequestOptions {
  params?: Record<string, Object>;
  headers?: Record<string, string>;
}

export class HttpClient {
  private static instance: HttpClient;
  private static backend: HttpBackend | null = null;
  private baseUrl: string = '';
  private token: string = '';
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private errors: ErrorManager = ErrorManager.getInstance();
  private interceptors: HttpInterceptor[] = [];

  private constructor(backend: HttpBackend | null = null) {
    if (backend) {
      HttpClient.backend = backend;
    }
  }

  /** 生产环境单例 */
  static getInstance(): HttpClient {
    if (!HttpClient.instance) {
      HttpClient.instance = new HttpClient();
    }
    return HttpClient.instance;
  }

  /** 测试用：注入 mock backend 创建实例 */
  static getInstanceWithBackend(backend: HttpBackend): HttpClient {
    HttpClient.backend = backend;
    HttpClient.instance = new HttpClient(backend);
    return HttpClient.instance;
  }

  /** 设置后端（生产环境由 HttpAdapter 调用） */
  setBackend(backend: HttpBackend): void {
    HttpClient.backend = backend;
  }

  setBaseUrl(url: string): void {
    this.baseUrl = url.endsWith('/') ? url.slice(0, -1) : url;
  }

  setToken(token: string): void {
    this.token = token;
  }

  addInterceptor(interceptor: HttpInterceptor): void {
    this.interceptors.push(interceptor);
  }

  /** GET 请求 */
  async get<T>(url: string, params?: Record<string, Object>): Promise<ApiResponse<T>> {
    return this.request<T>('GET', url, null, params);
  }

  /** POST 请求 */
  async post<T>(url: string, data: Object): Promise<ApiResponse<T>> {
    return this.request<T>('POST', url, data);
  }

  /** PUT 请求 */
  async put<T>(url: string, data: Object): Promise<ApiResponse<T>> {
    return this.request<T>('PUT', url, data);
  }

  /** DELETE 请求 */
  async delete<T>(url: string): Promise<ApiResponse<T>> {
    return this.request<T>('DELETE', url, null);
  }

  /** 核心请求方法 */
  private async request<T>(
    method: string,
    url: string,
    body: Object | null,
    params?: Record<string, Object>,
  ): Promise<ApiResponse<T>> {
    const fullUrl = this.buildUrl(url, params);
    const headers = this.buildHeaders(body);

    // 拦截器前置
    for (const i of this.interceptors) {
      if (i.before) i.before(headers);
    }

    this.logger.debug('HttpClient', `${method} ${fullUrl}`);

    try {
      if (!HttpClient.backend) {
        throw new Error('HttpBackend 未设置，请调用 setBackend 或 getInstanceWithBackend');
      }
      const response = await HttpClient.backend.request(method, fullUrl, body, headers);

      // 拦截器后置
      for (const i of this.interceptors) {
        if (i.after) i.after(response);
      }

      // 401：分发事件，抛错
      if (response.status === 401) {
        this.bus.emit('auth:unauthorized', { url });
        const err = this.errors.fromHttpStatus(401, '未授权');
        throw err;
      }

      // 429：分发限流事件
      if (response.status === 429) {
        this.bus.emit('api:rate-limited', { url });
      }

      return response.data as ApiResponse<T>;
    } catch (e) {
      this.logger.error('HttpClient', `${method} ${url} 失败`, e as Error);
      if ((e as AppError).code) {
        throw e;
      }
      // 网络错误
      this.bus.emit('network:error', { url, error: (e as Error).message });
      throw this.errors.fromError(e as Error, ErrorCategory.NETWORK);
    }
  }

  /** 构建完整 URL（带 query params） */
  private buildUrl(path: string, params?: Record<string, Object>): string {
    let url = path.startsWith('http') ? path : `${this.baseUrl}${path.startsWith('/') ? path : '/' + path}`;
    if (params && Object.keys(params).length > 0) {
      const query = Object.entries(params)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&');
      url += (url.includes('?') ? '&' : '?') + query;
    }
    return url;
  }

  /** 构建请求头 */
  private buildHeaders(body: Object | null): Record<string, string> {
    const headers: Record<string, string> = {
      'X-Request-ID': this.generateRequestId(),
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }
    if (body !== null) {
      headers['Content-Type'] = 'application/json';
    }
    return headers;
  }

  /** 生成请求 ID */
  private generateRequestId(): string {
    const ts = Date.now().toString(36);
    const rand = Math.random().toString(36).slice(2, 10);
    return `${ts}-${rand}`;
  }

  /** 测试用：获取 EventBus 引用 */
  getEventBusForTest(): EventBus {
    return this.bus;
  }
}

/**
 * AuthApi - 认证 API 模块
 *
 * 职责：注册、登录、登出、token 刷新、当前用户信息
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, User, AuthTokens, LoginForm, RegisterResult } from '../../types';

/** 注册请求体 */
export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

/** 刷新 token 请求体 */
export interface RefreshTokenRequest {
  refresh_token: string;
}

/** 裸对象判定：无信封字段（code/data），且携带目标类型的全部探针字段 */
function isBareShape(res: Object, probeKeys: string[]): boolean {
  const keys: string[] = Object.keys(res);
  if (keys.indexOf('code') !== -1 || keys.indexOf('data') !== -1) {
    return false;
  }
  for (const k of probeKeys) {
    if (keys.indexOf(k) === -1) {
      return false;
    }
  }
  return true;
}

/** 后端部分认证端点返回**裸对象**（无 code/data 信封）——在边界归一为 ApiResponse */
function asEnvelope<T>(res: ApiResponse<T>, probeKeys: string[]): ApiResponse<T> {
  if (isBareShape(res, probeKeys)) {
    const data = res as Object as T;
    const wrapped: ApiResponse<T> = { code: 0, message: 'ok', data: data };
    return wrapped;
  }
  return res;
}

export class AuthApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 注册：POST /auth/register */
  async register(data: RegisterRequest): Promise<ApiResponse<RegisterResult>> {
    return this.client.post<RegisterResult>('/auth/register', data);
  }

  /** 登录：后端返回裸 token 对象，归一为 ApiResponse 供页面统一判别 */
  async login(form: LoginForm): Promise<ApiResponse<AuthTokens>> {
    const res = await this.client.post<AuthTokens>('/auth/login', form);
    return asEnvelope<AuthTokens>(res, ['access_token']);
  }

  /** 登出 */
  async logout(): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>('/auth/logout', body);
  }

  /** 刷新 token：响应同为裸对象，归一 */
  async refresh(refreshToken: string): Promise<ApiResponse<AuthTokens>> {
    const body: RefreshTokenRequest = { refresh_token: refreshToken };
    const res = await this.client.post<AuthTokens>('/auth/refresh', body);
    return asEnvelope<AuthTokens>(res, ['access_token']);
  }

  /** 获取当前用户信息：后端返回裸用户对象，同样归一 */
  async me(): Promise<ApiResponse<User>> {
    const res = await this.client.get<User>('/auth/me');
    return asEnvelope<User>(res, ['username']);
  }
}

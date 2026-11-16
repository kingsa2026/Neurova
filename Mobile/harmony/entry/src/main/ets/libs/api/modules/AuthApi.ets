/**
 * AuthApi - 认证 API 模块
 *
 * 职责：注册、登录、登出、token 刷新、当前用户信息
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
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

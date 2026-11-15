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

export class AuthApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 注册：POST /v1/auth/register */
  async register(data: RegisterRequest): Promise<ApiResponse<RegisterResult>> {
    return this.client.post<RegisterResult>('/v1/auth/register', data);
  }

  /** 登录 */
  async login(form: LoginForm): Promise<ApiResponse<AuthTokens>> {
    return this.client.post<AuthTokens>('/v1/auth/login', form);
  }

  /** 登出 */
  async logout(): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>('/v1/auth/logout', body);
  }

  /** 刷新 token */
  async refresh(refreshToken: string): Promise<ApiResponse<AuthTokens>> {
    const body: RefreshTokenRequest = { refresh_token: refreshToken };
    return this.client.post<AuthTokens>('/v1/auth/refresh', body);
  }

  /** 获取当前用户信息 */
  async me(): Promise<ApiResponse<User>> {
    return this.client.get<User>('/v1/auth/me');
  }
}

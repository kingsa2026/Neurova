/**
 * SessionsApi - 会话 API 模块
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Session, PageResult, PageParams } from '../../types';

/** 创建会话请求体 */
export interface SessionCreateRequest {
  title?: string;
}

export class SessionsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  async list(agentId: string, params?: PageParams): Promise<ApiResponse<PageResult<Session>>> {
    return this.client.get<PageResult<Session>>(
      `/v1/agents/${agentId}/sessions`,
      params as Record<string, Object>,
    );
  }

  async create(agentId: string, title?: string): Promise<ApiResponse<Session>> {
    const body: SessionCreateRequest = { title };
    return this.client.post<Session>(`/v1/agents/${agentId}/sessions`, body);
  }

  async get(sessionId: string): Promise<ApiResponse<Session>> {
    return this.client.get<Session>(`/v1/sessions/${sessionId}`);
  }

  async remove(sessionId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/sessions/${sessionId}`);
  }
}

/**
 * SessionsApi - 会话 API 模块
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Session, PageResult, PageParams } from '../../types';

export class SessionsApi {
  constructor(private client: HttpClient) {}

  async list(agentId: string, params?: PageParams): Promise<ApiResponse<PageResult<Session>>> {
    return this.client.get<PageResult<Session>>(
      `/v1/agents/${agentId}/sessions`,
      params as Record<string, Object>,
    );
  }

  async create(agentId: string, title?: string): Promise<ApiResponse<Session>> {
    return this.client.post<Session>(`/v1/agents/${agentId}/sessions`, { title });
  }

  async get(sessionId: string): Promise<ApiResponse<Session>> {
    return this.client.get<Session>(`/v1/sessions/${sessionId}`);
  }

  async remove(sessionId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/sessions/${sessionId}`);
  }
}

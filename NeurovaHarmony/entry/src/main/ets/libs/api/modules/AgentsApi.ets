/**
 * AgentsApi - Agent API 模块
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Agent, PageResult, PageParams } from '../../types';

export class AgentsApi {
  constructor(private client: HttpClient) {}

  async list(params?: PageParams): Promise<ApiResponse<PageResult<Agent>>> {
    return this.client.get<PageResult<Agent>>('/v1/agents', params as Record<string, Object>);
  }

  async get(agentId: string): Promise<ApiResponse<Agent>> {
    return this.client.get<Agent>(`/v1/agents/${agentId}`);
  }

  async create(data: Partial<Agent>): Promise<ApiResponse<Agent>> {
    return this.client.post<Agent>('/v1/agents', data);
  }

  async update(agentId: string, data: Partial<Agent>): Promise<ApiResponse<Agent>> {
    return this.client.put<Agent>(`/v1/agents/${agentId}`, data);
  }

  async remove(agentId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/agents/${agentId}`);
  }
}

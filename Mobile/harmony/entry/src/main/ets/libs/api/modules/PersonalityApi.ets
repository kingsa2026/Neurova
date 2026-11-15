/**
 * PersonalityApi - 个性层 API 模块
 *
 * 职责：封装情绪（Emotion）与个性（Personality）资源的查询、创建、删除、重置操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().personality;
 *   const page = await api.listEmotions('agent-1', { page: 1, size: 20 });
 *   const current = await api.getCurrentEmotion('agent-1');
 *   const p = await api.getPersonality('agent-1');
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Emotion, Personality, PageResult, PageParams } from '../../types';

export class PersonalityApi {
  constructor(private client: HttpClient) {}

  /** 列出某 Agent 的情绪记录（支持分页） */
  async listEmotions(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Emotion>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Emotion>>('/v1/personality/emotions', query);
  }

  /** 获取单条情绪记录 */
  async getEmotion(id: string): Promise<ApiResponse<Emotion>> {
    return this.client.get<Emotion>(`/v1/personality/emotions/${id}`);
  }

  /** 创建情绪记录 */
  async createEmotion(data: Partial<Emotion>): Promise<ApiResponse<Emotion>> {
    return this.client.post<Emotion>('/v1/personality/emotions', data);
  }

  /** 删除情绪记录 */
  async removeEmotion(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/personality/emotions/${id}`);
  }

  /** 获取某 Agent 当前情绪 */
  async getCurrentEmotion(agentId: string): Promise<ApiResponse<Emotion>> {
    return this.client.get<Emotion>('/v1/personality/emotions/current', { agentId });
  }

  /** 获取某 Agent 的个性维度 */
  async getPersonality(agentId: string): Promise<ApiResponse<Personality>> {
    return this.client.get<Personality>('/v1/personality', { agentId });
  }

  /** 更新个性维度（agentId 注入到 body） */
  async updatePersonality(
    agentId: string,
    data: Partial<Personality>,
  ): Promise<ApiResponse<Personality>> {
    const body: Partial<Personality> & { agentId: string } = { ...data, agentId };
    return this.client.put<Personality>('/v1/personality', body);
  }

  /** 重置某 Agent 个性到默认值 */
  async resetPersonality(agentId: string): Promise<ApiResponse<Personality>> {
    return this.client.post<Personality>('/v1/personality/reset', { agentId });
  }
}

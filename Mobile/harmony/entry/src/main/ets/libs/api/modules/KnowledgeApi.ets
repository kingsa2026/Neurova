/**
 * KnowledgeApi - 知识库 API 模块
 *
 * 职责：封装知识库资源的 CRUD 与搜索操作
 * 设计：通过 HttpClient 委托请求；query 序列化为 GET 参数；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().knowledge;
 *   const page = await api.list({ keyword: 'AI' });
 *   const hit = await api.search('关键词', 'agent-1', 10);
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  KnowledgeItem,
  KnowledgeQuery,
  PageResult,
} from '../../types';

/** 知识搜索请求体 */
export interface KnowledgeSearchRequest {
  keyword: string;
  agentId?: string;
  limit?: number;
}

export class KnowledgeApi {
  constructor(private client: HttpClient) {}

  /** 列出知识（按 KnowledgeQuery 过滤，支持分页） */
  async list(query?: KnowledgeQuery): Promise<ApiResponse<PageResult<KnowledgeItem>>> {
    const params: Record<string, Object> = {};
    if (query) {
      if (query.keyword !== undefined) params['keyword'] = query.keyword;
      if (query.category !== undefined) params['category'] = query.category;
      if (query.tags && query.tags.length > 0) params['tags'] = query.tags.join(',');
      if (query.agentId !== undefined) params['agentId'] = query.agentId;
      if (query.status !== undefined) params['status'] = query.status;
      if (query.page !== undefined) params['page'] = query.page;
      if (query.size !== undefined) params['size'] = query.size;
    }
    return this.client.get<PageResult<KnowledgeItem>>('/v1/knowledge', params);
  }

  /** 获取单条知识 */
  async get(knowledgeId: string): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.get<KnowledgeItem>(`/v1/knowledge/${knowledgeId}`);
  }

  /** 创建知识 */
  async create(data: Partial<KnowledgeItem>): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.post<KnowledgeItem>('/v1/knowledge', data);
  }

  /** 更新知识 */
  async update(knowledgeId: string, data: Partial<KnowledgeItem>): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.put<KnowledgeItem>(`/v1/knowledge/${knowledgeId}`, data);
  }

  /** 删除知识 */
  async remove(knowledgeId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/knowledge/${knowledgeId}`);
  }

  /** 搜索知识（关键词 + 可选 agentId + 限制数量） */
  async search(
    keyword: string,
    agentId?: string,
    limit?: number,
  ): Promise<ApiResponse<KnowledgeItem[]>> {
    const body: KnowledgeSearchRequest = { keyword };
    if (agentId !== undefined) body.agentId = agentId;
    if (limit !== undefined) body.limit = limit;
    return this.client.post<KnowledgeItem[]>('/v1/knowledge/search', body);
  }
}

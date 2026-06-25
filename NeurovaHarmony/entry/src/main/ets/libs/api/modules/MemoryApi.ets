/**
 * MemoryApi - 记忆管理 API 模块
 *
 * 职责：封装记忆资源的 CRUD 与搜索操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().memory;
 *   const page = await api.list('agent-1', 'episodic', { page: 1, size: 20 });
 *   const hit = await api.search({ keyword: '关键词', agentId: 'agent-1', limit: 5 });
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Memory, MemoryType, PageResult, PageParams } from '../../types';

/** 记忆搜索请求参数 */
export interface MemorySearchQuery {
  agentId?: string;
  keyword: string;
  limit?: number;
}

export class MemoryApi {
  constructor(private client: HttpClient) {}

  /** 列出记忆（可选 agentId / type 过滤，支持分页） */
  async list(
    agentId?: string,
    type?: MemoryType,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Memory>>> {
    const query: Record<string, Object> = {};
    if (agentId) query['agentId'] = agentId;
    if (type) query['type'] = type;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Memory>>('/v1/memory', query);
  }

  /** 获取单条记忆 */
  async get(memoryId: string): Promise<ApiResponse<Memory>> {
    return this.client.get<Memory>(`/v1/memory/${memoryId}`);
  }

  /** 创建记忆 */
  async create(data: Partial<Memory>): Promise<ApiResponse<Memory>> {
    return this.client.post<Memory>('/v1/memory', data);
  }

  /** 更新记忆 */
  async update(memoryId: string, data: Partial<Memory>): Promise<ApiResponse<Memory>> {
    return this.client.put<Memory>(`/v1/memory/${memoryId}`, data);
  }

  /** 删除记忆 */
  async remove(memoryId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/memory/${memoryId}`);
  }

  /** 搜索记忆（关键词 + 可选 agentId + 限制数量） */
  async search(query: MemorySearchQuery): Promise<ApiResponse<Memory[]>> {
    return this.client.post<Memory[]>('/v1/memory/search', query);
  }
}

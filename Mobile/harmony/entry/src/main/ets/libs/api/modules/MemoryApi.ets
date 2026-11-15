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
import { ApiResponse, Memory, MemoryType, PageResult } from '../../types';

/** GET /memory 的 data 载荷（base.py memory_to_dict 投影子集） */
export interface MemoryItemDto {
  id: string;
  agent_id: string;
  content: string;
  category: string;
  type: string;
  temperature: number;
  importance: number;
  tags: string[];
}

/** GET /memory 的 data 包裹 */
export interface MemoryListPayload {
  count: number;
  memories: MemoryItemDto[];
}

export class MemoryApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 记忆列表/搜索（参数名以 crud.py 实测为准：query/agent_id/memory_type/limit） */
  async list(
    agentId?: string,
    type?: MemoryType,
    limit?: number,
    query?: string,
  ): Promise<ApiResponse<PageResult<Memory>>> {
    const parts: string[] = [];
    if (query && query.length > 0) {
      parts.push('query=' + encodeURIComponent(query));
    }
    if (agentId && agentId.length > 0) {
      parts.push('agent_id=' + encodeURIComponent(agentId));
    }
    if (type && type.length > 0) {
      parts.push('memory_type=' + encodeURIComponent(type));
    }
    parts.push('limit=' + (limit !== undefined ? limit : 50).toString());
    const res = await this.client.get<MemoryListPayload>('/memory?' + parts.join('&'));
    // 后端 data:{count, memories:[dict]} → 前端 PageResult<Memory>（items/total）
    if (res.code === 0 && res.data) {
      const items: Memory[] = [];
      const raw = res.data.memories;
      for (let i = 0; i < raw.length; i++) {
        const m = raw[i];
        items.push({
          id: m.id,
          type: m.type as MemoryType,
          content: m.content,
          agentId: m.agent_id,
          temperature: m.temperature,
          importance: m.importance,
          createdAt: '',
          updatedAt: '',
          tags: m.tags,
          metadata: {} as Record<string, Object>,
        });
      }
      const page: PageResult<Memory> = { items: items, total: res.data.count, page: 1, size: items.length };
      const mapped: ApiResponse<PageResult<Memory>> = { code: res.code, message: res.message, data: page };
      return mapped;
    }
    return { code: res.code, message: res.message, data: res.data as Object as PageResult<Memory> };
  }

  /** 获取单条记忆 */
  async get(memoryId: string): Promise<ApiResponse<Memory>> {
    return this.client.get<Memory>(`/memory/${memoryId}`);
  }

  /** 创建记忆 */
  async create(data: Partial<Memory>): Promise<ApiResponse<Memory>> {
    return this.client.post<Memory>('/memory', data);
  }

  /** 更新记忆 */
  async update(memoryId: string, data: Partial<Memory>): Promise<ApiResponse<Memory>> {
    return this.client.put<Memory>(`/memory/${memoryId}`, data);
  }

  /** 删除记忆 */
  async remove(memoryId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/memory/${memoryId}`);
  }

}

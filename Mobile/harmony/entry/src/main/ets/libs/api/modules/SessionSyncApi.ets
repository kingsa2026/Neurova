/**
 * SessionSyncApi - 会话同步 API 模块
 *
 * 职责：封装会话跨渠道同步资源的 CRUD 操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 覆盖实体：
 *   - SessionSync  会话同步记录（跨渠道消息同步状态）
 *
 * 用法：
 *   const api = ApiFacade.getInstance().sessionSync;
 *   const page = await api.list('agent-1', { page: 1, size: 20 });
 *   const triggered = await api.trigger('ss-1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
  SessionSync,
} from '../../types';

export class SessionSyncApi {
  constructor(private client: HttpClient) {}

  /** 列出会话同步记录（按 agentId 过滤，支持分页） */
  async list(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<SessionSync>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<SessionSync>>('/v1/session-syncs', query);
  }

  /** 获取单条会话同步记录 */
  async get(syncId: string): Promise<ApiResponse<SessionSync>> {
    return this.client.get<SessionSync>(`/v1/session-syncs/${syncId}`);
  }

  /** 创建会话同步记录 */
  async create(data: Partial<SessionSync>): Promise<ApiResponse<SessionSync>> {
    return this.client.post<SessionSync>('/v1/session-syncs', data);
  }

  /** 更新会话同步记录 */
  async update(
    syncId: string,
    data: Partial<SessionSync>,
  ): Promise<ApiResponse<SessionSync>> {
    return this.client.put<SessionSync>(`/v1/session-syncs/${syncId}`, data);
  }

  /** 删除会话同步记录 */
  async remove(syncId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/session-syncs/${syncId}`);
  }

  /** 触发同步（手动重试） */
  async trigger(syncId: string): Promise<ApiResponse<{ ok: boolean; syncedAt: string }>> {
    return this.client.post<{ ok: boolean; syncedAt: string }>(
      `/v1/session-syncs/${syncId}/trigger`,
      {},
    );
  }
}

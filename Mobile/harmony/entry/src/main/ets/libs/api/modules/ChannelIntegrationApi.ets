/**
 * ChannelIntegrationApi - 渠道集成 API 模块
 *
 * 职责：封装渠道集成资源的 CRUD 操作（扩展 ChannelInfo，覆盖多渠道协同场景）
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 覆盖实体：
 *   - ChannelIntegration  渠道集成（连接/同步/能力配置）
 *
 * 用法：
 *   const api = ApiFacade.getInstance().channelIntegration;
 *   const page = await api.list('agent-1', { page: 1, size: 20 });
 *   const item = await api.get('ci-1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
  ChannelIntegration,
  IntegrationStatus,
} from '../../types';

/** 列表查询参数：分页 + 状态筛选（替代 PageParams & { status } 交叉类型） */
interface ChannelIntegrationListParams extends PageParams {
  status?: IntegrationStatus;
}

/** 连通性测试结果 */
interface ConnectionTestResult {
  ok: boolean;
  latencyMs?: number;
}

export class ChannelIntegrationApi {
  private client: HttpClient;
  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 列出渠道集成（按 agentId 过滤，支持分页 + 状态筛选） */
  async list(
    agentId: string,
    params?: ChannelIntegrationListParams,
  ): Promise<ApiResponse<PageResult<ChannelIntegration>>> {
    const query: Record<string, Object> = {};
    query['agentId'] = agentId;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
      if (params.status !== undefined) query['status'] = params.status;
    }
    return this.client.get<PageResult<ChannelIntegration>>('/v1/channel-integrations', query);
  }

  /** 获取单条渠道集成 */
  async get(integrationId: string): Promise<ApiResponse<ChannelIntegration>> {
    return this.client.get<ChannelIntegration>(`/v1/channel-integrations/${integrationId}`);
  }

  /** 创建渠道集成 */
  async create(data: Partial<ChannelIntegration>): Promise<ApiResponse<ChannelIntegration>> {
    return this.client.post<ChannelIntegration>('/v1/channel-integrations', data);
  }

  /** 更新渠道集成 */
  async update(
    integrationId: string,
    data: Partial<ChannelIntegration>,
  ): Promise<ApiResponse<ChannelIntegration>> {
    return this.client.put<ChannelIntegration>(
      `/v1/channel-integrations/${integrationId}`,
      data,
    );
  }

  /** 删除渠道集成 */
  async remove(integrationId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/channel-integrations/${integrationId}`);
  }

  /** 测试渠道连通性（触发后端 ping） */
  async testConnection(integrationId: string): Promise<ApiResponse<ConnectionTestResult>> {
    const body: Record<string, Object> = {};
    return this.client.post<ConnectionTestResult>(
      `/v1/channel-integrations/${integrationId}/test`,
      body,
    );
  }
}

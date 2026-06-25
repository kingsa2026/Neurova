/**
 * AgentChannelsApi - Agent 渠道管理 API 模块
 *
 * 职责：封装 Agent 嵌套渠道资源的 CRUD、连接测试、启停切换
 * 设计：通过 HttpClient 委托请求；嵌套路径 /v1/agents/{agentId}/channels/...；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().agentChannels;
 *   const channels = await api.list('a1');
 *   const r = await api.testConnection('a1', 'c1');
 *   await api.toggle('a1', 'c1', false);
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, ChannelInfo } from '../../types';

/** 渠道连接测试结果 */
export interface ChannelTestResult {
  success: boolean;
  message: string;
}

/** 渠道启停切换请求体 */
export interface ChannelToggleBody {
  enabled: boolean;
}

export class AgentChannelsApi {
  constructor(private client: HttpClient) {}

  /** 列出某 Agent 的所有渠道 */
  async list(agentId: string): Promise<ApiResponse<ChannelInfo[]>> {
    return this.client.get<ChannelInfo[]>(`/v1/agents/${agentId}/channels`);
  }

  /** 获取单条渠道 */
  async get(agentId: string, channelId: string): Promise<ApiResponse<ChannelInfo>> {
    return this.client.get<ChannelInfo>(`/v1/agents/${agentId}/channels/${channelId}`);
  }

  /** 为某 Agent 创建渠道 */
  async create(agentId: string, data: Partial<ChannelInfo>): Promise<ApiResponse<ChannelInfo>> {
    return this.client.post<ChannelInfo>(`/v1/agents/${agentId}/channels`, data);
  }

  /** 更新渠道 */
  async update(
    agentId: string,
    channelId: string,
    data: Partial<ChannelInfo>,
  ): Promise<ApiResponse<ChannelInfo>> {
    return this.client.put<ChannelInfo>(`/v1/agents/${agentId}/channels/${channelId}`, data);
  }

  /** 删除渠道 */
  async remove(agentId: string, channelId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/agents/${agentId}/channels/${channelId}`);
  }

  /** 测试渠道连接 */
  async testConnection(
    agentId: string,
    channelId: string,
  ): Promise<ApiResponse<ChannelTestResult>> {
    return this.client.post<ChannelTestResult>(
      `/v1/agents/${agentId}/channels/${channelId}/test`,
      {},
    );
  }

  /** 切换渠道启用状态 */
  async toggle(
    agentId: string,
    channelId: string,
    enabled: boolean,
  ): Promise<ApiResponse<ChannelInfo>> {
    const body: ChannelToggleBody = { enabled };
    return this.client.put<ChannelInfo>(
      `/v1/agents/${agentId}/channels/${channelId}/toggle`,
      body,
    );
  }
}

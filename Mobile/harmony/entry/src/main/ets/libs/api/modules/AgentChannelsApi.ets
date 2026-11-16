/**
 * AgentChannelsApi - Agent 渠道管理 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源：/v1/agents/{id}/channels 嵌套资源**不存在**（agent.py 仅有
 * stats/switch/constitution/decision/rebuild-loop）；Agent 名下渠道的真实管理面是
 * channel_config.py @ /v1/channel-configs?agent_id=（agent 隔离多实例）：
 *   GET    ""?agent_id=           → ChannelConfigResponse[]
 *   POST   ""?agent_id=           → upsert（ChannelConfigRequest 契约）
 *   DELETE /{channel_type}?agent_id=
 *   POST   /{channel_type}/test?agent_id= → ChannelTestResult
 * 本模块按该事实源封装；旧 /agents/{id}/channels 形态的方法一律 throw 点名。
 */

import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import { ApiResponse } from '../../types';
import { ChannelConfigDto, ChannelConfigUpsertBody, ChannelTestResultDto, emptyExtra } from './ChannelIntegrationApi';

export type { ChannelConfigDto, ChannelConfigUpsertBody, ChannelTestResultDto };
export { emptyExtra };

/** 渠道连接测试结果（兼容旧导出名） */
export interface ChannelTestResult {
  success: boolean;
  message: string;
}

export class AgentChannelsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 列出某 Agent 名下的渠道配置（GET /channel-configs?agent_id=，后端裸数组边界归一） */
  async list(agentId: string): Promise<ApiResponse<ChannelConfigDto[]>> {
    const query: Record<string, Object> = { 'agent_id': agentId };
    const res = asEnvelopeList<ChannelConfigDto>(await this.client.get<ChannelConfigDto[]>('/channel-configs', query));
    const arr = (res.data ?? []) as ChannelConfigDto[];
    return { code: res.code, message: res.message, data: arr } as ApiResponse<ChannelConfigDto[]>;
  }

  /** 为某 Agent 保存（创建/更新）渠道配置（POST /channel-configs?agent_id=，{success,...} 裸 dict 边界归一） */
  async create(agentId: string, body: ChannelConfigUpsertBody): Promise<ApiResponse<Object>> {
    const res = await this.client.post<Object>(`/channel-configs?agent_id=${encodeURIComponent(agentId)}`, body);
    return asEnvelope<Object>(res, ['success']) as ApiResponse<Object>;
  }

  /** 删除某 Agent 名下的指定渠道配置（DELETE /channel-configs/{channel_type}?agent_id=，{success,...} 裸 dict 边界归一） */
  async remove(agentId: string, channelType: string): Promise<ApiResponse<Object>> {
    const res = await this.client.delete<Object>(`/channel-configs/${channelType}?agent_id=${encodeURIComponent(agentId)}`);
    return asEnvelope<Object>(res, ['success']) as ApiResponse<Object>;
  }

  /** 测试某 Agent 渠道连接（POST /channel-configs/{channel_type}/test?agent_id=，用掩码外凭据空跑；ChannelTestResult 裸对象边界归一） */
  async testConnection(agentId: string, channelType: string): Promise<ApiResponse<ChannelTestResult>> {
    const body: ChannelConfigUpsertBody = {
      channel_type: channelType,
      enabled: true,
      app_id: '',
      app_secret: '',
      use_stream: true,
      webhook_url: '',
      webhook_token: '',
      encrypt_key: '',
      verification_token: '',
      extra: emptyExtra(),
    };
    const res = asEnvelope<Object>(await this.client.post<Object>(
      `/channel-configs/${channelType}/test?agent_id=${encodeURIComponent(agentId)}`, body), ['success', 'message']);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const result: ChannelTestResult = {
      success: payload['success'] === true,
      message: String(payload['message'] ?? ''),
    };
    return { code: res.code, message: res.message, data: result } as ApiResponse<ChannelTestResult>;
  }

  /** @deprecated 后端无 GET /agents/{id}/channels/{cid}（详情经 list 整表返回） */
  async get(agentId: string, channelId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：GET /v1/agents/{id}/channels/{cid}（Agent 渠道实为 /v1/channel-configs?agent_id=）');
  }

  /** @deprecated 后端无 PUT /agents/{id}/channels/{cid}（更新走 create 的 upsert 语义） */
  async update(agentId: string, channelId: string, data: Object): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：PUT /v1/agents/{id}/channels/{cid}（更新走 create 的 upsert 语义）');
  }

  /** @deprecated 后端无 PUT /agents/{id}/channels/{cid}/toggle（启停由配置 enabled 字段在保存时生效） */
  async toggle(agentId: string, channelId: string, enabled: boolean): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：PUT /v1/agents/{id}/channels/{cid}/toggle（启停由渠道配置 enabled 字段在保存时生效）');
  }
}

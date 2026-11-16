/**
 * ChannelIntegrationApi - 渠道域 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py；旧 /channel-integrations 端点不存在，全部退役）：
 *   channel_config.py @ /v1/channel-configs（自述前缀）：
 *     GET    ""?agent_id= → ChannelConfigResponse[]（channel_type/agent_id/enabled/
 *                            app_id_masked/use_stream/connected/extra）
 *     POST   ""?agent_id=（ChannelConfigRequest 契约，upsert）→ {success,channel_type,agent_id,message,needs_scan}
 *     DELETE /{channel_type}?agent_id= → {success,message,agent_id}
 *     POST   /{channel_type}/test?agent_id= → ChannelTestResult{success,message,needs_scan,details}
 *   channels.py @ /v1/channel-adapters：
 *     GET "" → {running, adapters:{...}}（全量实例健康视图）
 *     GET /health/all、GET /conflicts/check
 *   channel_sharing.py @ /v1/channel-sharing：
 *     GET /status、GET /available-channels、POST /channels、POST /enable、POST /disable
 */

import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
} from '../../types';

/** 渠道配置（channel_config.ChannelConfigResponse 逐字段投影） */
export interface ChannelConfigDto {
  channel_type: string;
  agent_id: string;
  enabled: boolean;
  app_id_masked: string;
  use_stream: boolean;
  connected: boolean;
  extra: Record<string, Object>;
}

/** 渠道配置 upsert body（channel_config.ChannelConfigRequest 契约，蛇形字段） */
export interface ChannelConfigUpsertBody {
  channel_type: string;
  enabled: boolean;
  app_id: string;
  app_secret: string;
  use_stream: boolean;
  webhook_url: string;
  webhook_token: string;
  encrypt_key: string;
  verification_token: string;
  extra: Record<string, Object>;
}

/** 连接测试结果（channel_config.ChannelTestResult 投影） */
export interface ChannelTestResultDto {
  success: boolean;
  message: string;
  needs_scan: boolean;
  details: Record<string, Object>;
}

/** 保存渠道配置结果（create_or_update_config 投影） */
export interface ChannelSaveResultDto {
  success: boolean;
  channel_type: string;
  agent_id: string;
  message: string;
  needs_scan: boolean;
}

/** 适配器健康视图（channels.list_channels → manager.health_check 投影） */
export interface AdapterHealthViewDto {
  running: boolean;
  adapters: Record<string, Object>;
}

/** 空extra便捷构造（ArkTS 禁非空字面量落 Record，集中一处） */
export function emptyExtra(): Record<string, Object> {
  const extra: Record<string, Object> = {};
  return extra;
}

export class ChannelIntegrationApi {
  private client: HttpClient;
  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 渠道配置列表（GET /channel-configs?agent_id=，裸数组包成 PageResult；params 仅保留签名，后端按 agent 整表返回） */
  async list(agentId?: string, params?: PageParams): Promise<ApiResponse<PageResult<ChannelConfigDto>>> {
    const query: Record<string, Object> = {};
    if (agentId !== undefined && agentId.length > 0) query['agent_id'] = agentId;
    const res = await this.client.get<ChannelConfigDto[]>('/channel-configs', query);
    const arr = (res.data ?? []) as ChannelConfigDto[];
    return {
      code: res.code, message: res.message,
      data: { items: arr, total: arr.length, page: 1, size: arr.length },
    } as ApiResponse<PageResult<ChannelConfigDto>>;
  }

  /** 获取单条渠道配置（GET /channel-configs/{channel_type}?agent_id=） */
  async getConfig(agentId: string, channelType: string): Promise<ApiResponse<ChannelConfigDto>> {
    const query: Record<string, Object> = { 'agent_id': agentId };
    return this.client.get<ChannelConfigDto>(`/channel-configs/${channelType}`, query);
  }

  /** 保存（创建/更新）渠道配置（POST /channel-configs?agent_id=，upsert） */
  async saveConfig(agentId: string, body: ChannelConfigUpsertBody): Promise<ApiResponse<ChannelSaveResultDto>> {
    const res = await this.client.post<Object>(`/channel-configs?agent_id=${encodeURIComponent(agentId)}`, body);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const result: ChannelSaveResultDto = {
      success: payload['success'] === true,
      channel_type: String(payload['channel_type'] ?? body.channel_type),
      agent_id: String(payload['agent_id'] ?? agentId),
      message: String(payload['message'] ?? ''),
      needs_scan: payload['needs_scan'] === true,
    };
    return { code: res.code, message: res.message, data: result } as ApiResponse<ChannelSaveResultDto>;
  }

  /** 删除渠道配置（DELETE /channel-configs/{channel_type}?agent_id=） */
  async removeConfig(agentId: string, channelType: string): Promise<ApiResponse<Object>> {
    const query: Record<string, Object> = { 'agent_id': agentId };
    return this.client.delete<Object>(`/channel-configs/${channelType}?agent_id=${encodeURIComponent(agentId)}`);
  }

  /** 测试渠道连接（POST /channel-configs/{channel_type}/test?agent_id=） */
  async testConfig(agentId: string, channelType: string, body: ChannelConfigUpsertBody): Promise<ApiResponse<ChannelTestResultDto>> {
    const res = await this.client.post<Object>(`/channel-configs/${channelType}/test?agent_id=${encodeURIComponent(agentId)}`, body);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const result: ChannelTestResultDto = {
      success: payload['success'] === true,
      message: String(payload['message'] ?? ''),
      needs_scan: payload['needs_scan'] === true,
      details: (payload['details'] ?? {}) as Record<string, Object>,
    };
    return { code: res.code, message: res.message, data: result } as ApiResponse<ChannelTestResultDto>;
  }

  /** 渠道适配器全量健康视图（GET /channel-adapters） */
  async listAdapters(): Promise<ApiResponse<AdapterHealthViewDto>> {
    return this.client.get<AdapterHealthViewDto>('/channel-adapters');
  }

  /** 全渠道健康检查（GET /channel-adapters/health/all） */
  async adaptersHealthAll(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/channel-adapters/health/all');
  }

  /** 渠道上下文共享状态摘要（GET /channel-sharing/status） */
  async sharingStatus(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/channel-sharing/status');
  }

  /** 可用渠道清单（GET /channel-sharing/available-channels） */
  async availableChannels(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/channel-sharing/available-channels');
  }

  /** @deprecated 后端无 GET /channel-integrations/{id}（渠道面实际为 /channel-configs 与 /channel-adapters） */
  async get(integrationId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：GET /v1/channel-integrations/{id}（渠道域实际为 /v1/channel-configs）');
  }

  /** @deprecated 后端无 POST /channel-integrations */
  async create(data: Object): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：POST /v1/channel-integrations（保存渠道配置走 saveConfig → POST /v1/channel-configs）');
  }

  /** @deprecated 后端无 PUT /channel-integrations/{id} */
  async update(integrationId: string, data: Object): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：PUT /v1/channel-integrations/{id}（更新渠道配置走 saveConfig → POST /v1/channel-configs）');
  }

  /** @deprecated 后端无 DELETE /channel-integrations/{id} */
  async remove(integrationId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/channel-integrations/{id}（删除渠道配置走 removeConfig → DELETE /v1/channel-configs/{type}）');
  }

  /** @deprecated 后端无 POST /channel-integrations/{id}/test */
  async testConnection(integrationId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：POST /v1/channel-integrations/{id}/test（测试走 testConfig → POST /v1/channel-configs/{type}/test）');
  }
}

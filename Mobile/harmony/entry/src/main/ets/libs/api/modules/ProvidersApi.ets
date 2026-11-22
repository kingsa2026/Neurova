/**
 * ProvidersApi - 服务商与模型管理 API 模块（同源 PC ModelPage，对照原型 F11）
 *
 * 后端事实源：neurova/api/endpoints/provider.py（挂 /v1/providers）：
 *   GET    /providers                       → **裸数组** List[ProviderInfo]（无信封）
 *   GET    /providers/active-model          → {code:0,data:{model,provider}}
 *   POST   /providers/activate-model        → {provider_id,model_id}
 *   POST   /providers/{id}/check-connection → {code:0,data:{connected,message?}}
 *   POST   /providers                       → CreateProviderRequest
 *   PUT    /providers/{id}                  → UpdateProviderRequest
 *   DELETE /providers/{id}
 * 模型清单：GET /v1/models → **裸数组** List[ModelInfo]（model.py:167），
 *           POST /v1/models/probe-multimodal 能力探测（对照 PC）。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 服务商（provider.py ProviderInfo 投影） */
export interface ProviderInfoDto {
  provider_id: string;
  name: string;
  provider_type: string;
  base_url: string;
  is_active: boolean;
  status: string;
  models_count: number;
  health: string;
  api_key_configured: boolean;
  /** D-R2：同优先级组内加权分流份额（0=仅兜底；缺省 1） */
  weight: number;
  /** R11：服务商级嵌入模型声明（空串=未声明=本地嵌入） */
  embedding_model: string;
}

/** 活跃模型载荷（provider.py /active-model） */
export interface ActiveModelDto {
  model: string | null;
  provider: string | null;
}

/** 连通性探测载荷 */
export interface CheckConnectionDto {
  connected: boolean;
  message: string;
}

/** 创建服务商请求（provider.py CreateProviderRequest；weight/embedding_model 选填） */
export interface ProviderCreateRequest {
  name: string;
  provider_type: string;
  base_url: string;
  api_key: string;
  weight?: number;
  embedding_model?: string;
}

/** 服务商流量分布行（/stats/usage-overview 的 by_provider 段；D-R2 观测项） */
export interface ProviderTrafficRowDto {
  provider: string;
  calls: number;
  tokens: number;
  /** tokens 占比（百分比一位小数） */
  share: number;
}

/** 模型（model.py ModelInfo 投影子集） */
export interface ModelInfoDto {
  model_id: string;
  name: string;
  provider: string;
  capabilities: string[];
  context_window: number;
  max_tokens: number;
  is_active: boolean;
  status: string;
  connectable: boolean;
}

export class ProvidersApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 服务商列表（裸数组；逐项归一——缺字段会让我方渲染期 undefined.length 崩溃） */
  async list(): Promise<ProviderInfoDto[]> {
    const res = await this.client.get<ProviderInfoDto[]>('/providers');
    const arr = res as Object as ProviderInfoDto[];
    const out: ProviderInfoDto[] = [];
    for (const raw of arr) {
      const p = raw as Object as Record<string, Object>;
      const item: ProviderInfoDto = {
        provider_id: String(p['provider_id'] ?? ''),
        name: String(p['name'] ?? ''),
        provider_type: String(p['provider_type'] ?? ''),
        base_url: String(p['base_url'] ?? ''),
        is_active: p['is_active'] === true,
        status: String(p['status'] ?? ''),
        models_count: Number(p['models_count'] ?? 0),
        health: String(p['health'] ?? ''),
        api_key_configured: p['api_key_configured'] === true,
        weight: Number(p['weight'] ?? 1),
        embedding_model: String(p['embedding_model'] ?? ''),
      };
      out.push(item);
    }
    return out;
  }

  /** 模型清单（裸数组；逐项归一，capabilities 缺省空数组） */
  async listModels(): Promise<ModelInfoDto[]> {
    const res = await this.client.get<ModelInfoDto[]>('/models');
    const arr = res as Object as ModelInfoDto[];
    const out: ModelInfoDto[] = [];
    for (const raw of arr) {
      const m = raw as Object as Record<string, Object>;
      const capsRaw = (m['capabilities'] ?? []) as Object[];
      const caps: string[] = [];
      for (const c of capsRaw) {
        caps.push(String(c));
      }
      const item: ModelInfoDto = {
        model_id: String(m['model_id'] ?? ''),
        name: String(m['name'] ?? ''),
        provider: String(m['provider'] ?? ''),
        capabilities: caps,
        context_window: Number(m['context_window'] ?? 0),
        max_tokens: Number(m['max_tokens'] ?? 0),
        is_active: m['is_active'] === true,
        status: String(m['status'] ?? ''),
        connectable: m['connectable'] === true,
      };
      out.push(item);
    }
    return out;
  }

  /** 当前活跃模型 */
  async activeModel(): Promise<ApiResponse<ActiveModelDto>> {
    return this.client.get<ActiveModelDto>('/providers/active-model');
  }

  /** 激活模型 */
  async activate(providerId: string, modelId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {
      'provider_id': providerId,
      'model_id': modelId,
    };
    return this.client.post<Object>('/providers/activate-model', body);
  }

  /** 连通性测试 */
  async checkConnection(providerId: string): Promise<ApiResponse<CheckConnectionDto>> {
    const body: Record<string, Object> = {};
    return this.client.post<CheckConnectionDto>(`/providers/${providerId}/check-connection`, body);
  }

  /** 创建服务商（含 API Key；创建后可对 id 调 checkConnection 验证） */
  async create(data: ProviderCreateRequest): Promise<ApiResponse<ProviderInfoDto>> {
    return this.client.post<ProviderInfoDto>('/providers', data);
  }

  /** 更新服务商 */
  async update(providerId: string, data: ProviderCreateRequest): Promise<ApiResponse<ProviderInfoDto>> {
    return this.client.put<ProviderInfoDto>(`/providers/${providerId}`, data);
  }

  /** 删除服务商 */
  async remove(providerId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/providers/${providerId}`);
  }

  /** 服务商真实流量分布（D-R2 观测项：/stats/usage-overview 的 by_provider 段；
   *  端点/段缺失或空库 → 空数组，卡片隐藏） */
  async providerTraffic(): Promise<ProviderTrafficRowDto[]> {
    const res = await this.client.get<Object>('/stats/usage-overview?days=7&trend_days=7');
    const obj = res as Object as Record<string, Object>;
    const arr = (obj['by_provider'] ?? []) as Object[];
    const out: ProviderTrafficRowDto[] = [];
    for (const raw of arr) {
      const r = raw as Object as Record<string, Object>;
      out.push({
        provider: String(r['provider'] ?? ''),
        calls: Number(r['calls'] ?? 0),
        tokens: Number(r['tokens'] ?? 0),
        share: Number(r['share'] ?? 0),
      });
    }
    return out;
  }
}

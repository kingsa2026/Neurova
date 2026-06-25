/**
 * ModelsApi - LLM 模型与 Provider API 模块
 *
 * 职责：封装 Provider 增删改查、模型列表、默认配置、生成参数管理
 * 设计：通过 HttpClient 委托请求；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().models;
 *   const providers = await api.listProviders();
 *   await api.setDefault({ provider_id: 'p1', model_id: 'm1' });
 *   const params = await api.getGenerationParams();
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  Provider,
  ModelItem,
  DefaultLLMConfig,
  GenerationParams,
} from '../../types';

export class ModelsApi {
  constructor(private client: HttpClient) {}

  // ===== Provider CRUD =====

  /** 列出所有 Provider */
  async listProviders(): Promise<ApiResponse<Provider[]>> {
    return this.client.get<Provider[]>('/v1/models/providers');
  }

  /** 获取单个 Provider */
  async getProvider(providerId: string): Promise<ApiResponse<Provider>> {
    return this.client.get<Provider>(`/v1/models/providers/${providerId}`);
  }

  /** 创建 Provider */
  async createProvider(data: Partial<Provider>): Promise<ApiResponse<Provider>> {
    return this.client.post<Provider>('/v1/models/providers', data);
  }

  /** 更新 Provider */
  async updateProvider(providerId: string, data: Partial<Provider>): Promise<ApiResponse<Provider>> {
    return this.client.put<Provider>(`/v1/models/providers/${providerId}`, data);
  }

  /** 删除 Provider */
  async removeProvider(providerId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/models/providers/${providerId}`);
  }

  // ===== Models =====

  /** 列出模型（可选按 providerId 过滤） */
  async listModels(providerId?: string): Promise<ApiResponse<ModelItem[]>> {
    const params: Record<string, Object> = {};
    if (providerId) params['providerId'] = providerId;
    return this.client.get<ModelItem[]>('/v1/models', params);
  }

  // ===== Default Config =====

  /** 设置默认 LLM 配置 */
  async setDefault(config: DefaultLLMConfig): Promise<ApiResponse<Object>> {
    return this.client.put<Object>('/v1/models/default', config);
  }

  // ===== Generation Params =====

  /** 获取生成参数 */
  async getGenerationParams(): Promise<ApiResponse<GenerationParams>> {
    return this.client.get<GenerationParams>('/v1/models/params');
  }

  /** 更新生成参数 */
  async updateGenerationParams(params: GenerationParams): Promise<ApiResponse<Object>> {
    return this.client.put<Object>('/v1/models/params', params);
  }
}

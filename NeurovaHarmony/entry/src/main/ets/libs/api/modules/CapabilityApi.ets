/**
 * CapabilityApi - 能力层 API 模块
 *
 * 职责：封装能力层资源（规则/智能体文件/媒体资产）的 CRUD 操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 覆盖实体：
 *   - Rule        智能体规则
 *   - AgentFile   智能体文件
 *   - MediaAsset  媒体资产
 *
 * 用法：
 *   const api = ApiFacade.getInstance().capability;
 *   const page = await api.listRules('agent-1', { page: 1, size: 20 });
 *   const file = await api.getFile('file-1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
  Rule,
  AgentFile,
  MediaAsset,
} from '../../types';

export class CapabilityApi {
  constructor(private client: HttpClient) {}

  // ==================== Rule 规则 ====================

  /** 列出规则（按 agentId 过滤，支持分页） */
  async listRules(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Rule>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Rule>>('/v1/capability/rules', query);
  }

  /** 获取单条规则 */
  async getRule(ruleId: string): Promise<ApiResponse<Rule>> {
    return this.client.get<Rule>(`/v1/capability/rules/${ruleId}`);
  }

  /** 创建规则 */
  async createRule(data: Partial<Rule>): Promise<ApiResponse<Rule>> {
    return this.client.post<Rule>('/v1/capability/rules', data);
  }

  /** 更新规则 */
  async updateRule(ruleId: string, data: Partial<Rule>): Promise<ApiResponse<Rule>> {
    return this.client.put<Rule>(`/v1/capability/rules/${ruleId}`, data);
  }

  /** 删除规则 */
  async removeRule(ruleId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/capability/rules/${ruleId}`);
  }

  // ==================== AgentFile 智能体文件 ====================

  /** 列出智能体文件（按 agentId 过滤，支持分页） */
  async listFiles(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<AgentFile>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<AgentFile>>('/v1/capability/files', query);
  }

  /** 获取单条文件元数据 */
  async getFile(fileId: string): Promise<ApiResponse<AgentFile>> {
    return this.client.get<AgentFile>(`/v1/capability/files/${fileId}`);
  }

  /** 创建文件记录 */
  async createFile(data: Partial<AgentFile>): Promise<ApiResponse<AgentFile>> {
    return this.client.post<AgentFile>('/v1/capability/files', data);
  }

  /** 更新文件记录 */
  async updateFile(fileId: string, data: Partial<AgentFile>): Promise<ApiResponse<AgentFile>> {
    return this.client.put<AgentFile>(`/v1/capability/files/${fileId}`, data);
  }

  /** 删除文件记录 */
  async removeFile(fileId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/capability/files/${fileId}`);
  }

  // ==================== MediaAsset 媒体资产 ====================

  /** 列出媒体资产（按 agentId 过滤，支持分页） */
  async listMedia(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<MediaAsset>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<MediaAsset>>('/v1/capability/media', query);
  }

  /** 获取单条媒体资产 */
  async getMedia(mediaId: string): Promise<ApiResponse<MediaAsset>> {
    return this.client.get<MediaAsset>(`/v1/capability/media/${mediaId}`);
  }

  /** 创建媒体资产记录 */
  async createMedia(data: Partial<MediaAsset>): Promise<ApiResponse<MediaAsset>> {
    return this.client.post<MediaAsset>('/v1/capability/media', data);
  }

  /** 更新媒体资产记录 */
  async updateMedia(mediaId: string, data: Partial<MediaAsset>): Promise<ApiResponse<MediaAsset>> {
    return this.client.put<MediaAsset>(`/v1/capability/media/${mediaId}`, data);
  }

  /** 删除媒体资产记录 */
  async removeMedia(mediaId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/capability/media/${mediaId}`);
  }
}

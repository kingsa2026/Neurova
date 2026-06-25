/**
 * CognitionApi - 认知层 API 模块
 *
 * 职责：封装认知层资源（经验/知识图谱/元认知/反思/成长）的 CRUD 操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 覆盖实体：
 *   - Experience           经验知识
 *   - KnowledgeGraph       知识图谱（只读 getGraph）
 *   - MetacognitionRecord  元认知记录
 *   - ReflectionRecord     反思记录
 *   - GrowthRecord         成长记录
 *
 * 用法：
 *   const api = ApiFacade.getInstance().cognition;
 *   const page = await api.listExperiences('agent-1', { page: 1, size: 20 });
 *   const graph = await api.getKnowledgeGraph('agent-1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
  Experience,
  KnowledgeGraph,
  MetacognitionRecord,
  ReflectionRecord,
  GrowthRecord,
} from '../../types';

export class CognitionApi {
  constructor(private client: HttpClient) {}

  // ==================== Experience 经验 ====================

  /** 列出经验（按 agentId 过滤，支持分页） */
  async listExperiences(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Experience>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Experience>>('/v1/cognition/experiences', query);
  }

  /** 获取单条经验 */
  async getExperience(experienceId: string): Promise<ApiResponse<Experience>> {
    return this.client.get<Experience>(`/v1/cognition/experiences/${experienceId}`);
  }

  /** 创建经验 */
  async createExperience(data: Partial<Experience>): Promise<ApiResponse<Experience>> {
    return this.client.post<Experience>('/v1/cognition/experiences', data);
  }

  /** 更新经验 */
  async updateExperience(
    experienceId: string,
    data: Partial<Experience>,
  ): Promise<ApiResponse<Experience>> {
    return this.client.put<Experience>(`/v1/cognition/experiences/${experienceId}`, data);
  }

  /** 删除经验 */
  async removeExperience(experienceId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/cognition/experiences/${experienceId}`);
  }

  // ==================== KnowledgeGraph 知识图谱 ====================

  /** 获取 Agent 的知识图谱（节点+边） */
  async getKnowledgeGraph(agentId: string): Promise<ApiResponse<KnowledgeGraph>> {
    return this.client.get<KnowledgeGraph>('/v1/cognition/knowledge-graph', { agentId });
  }

  // ==================== Metacognition 元认知 ====================

  /** 列出元认知记录（按 agentId 过滤，支持分页） */
  async listMetacognitions(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<MetacognitionRecord>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<MetacognitionRecord>>('/v1/cognition/metacognitions', query);
  }

  /** 获取单条元认知记录 */
  async getMetacognition(metacognitionId: string): Promise<ApiResponse<MetacognitionRecord>> {
    return this.client.get<MetacognitionRecord>(`/v1/cognition/metacognitions/${metacognitionId}`);
  }

  /** 创建元认知记录 */
  async createMetacognition(
    data: Partial<MetacognitionRecord>,
  ): Promise<ApiResponse<MetacognitionRecord>> {
    return this.client.post<MetacognitionRecord>('/v1/cognition/metacognitions', data);
  }

  /** 更新元认知记录 */
  async updateMetacognition(
    metacognitionId: string,
    data: Partial<MetacognitionRecord>,
  ): Promise<ApiResponse<MetacognitionRecord>> {
    return this.client.put<MetacognitionRecord>(
      `/v1/cognition/metacognitions/${metacognitionId}`,
      data,
    );
  }

  /** 删除元认知记录 */
  async removeMetacognition(metacognitionId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/cognition/metacognitions/${metacognitionId}`);
  }

  // ==================== Reflection 反思 ====================

  /** 列出反思记录（按 agentId 过滤，支持分页） */
  async listReflections(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ReflectionRecord>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<ReflectionRecord>>('/v1/cognition/reflections', query);
  }

  /** 获取单条反思记录 */
  async getReflection(reflectionId: string): Promise<ApiResponse<ReflectionRecord>> {
    return this.client.get<ReflectionRecord>(`/v1/cognition/reflections/${reflectionId}`);
  }

  /** 创建反思记录 */
  async createReflection(data: Partial<ReflectionRecord>): Promise<ApiResponse<ReflectionRecord>> {
    return this.client.post<ReflectionRecord>('/v1/cognition/reflections', data);
  }

  /** 更新反思记录 */
  async updateReflection(
    reflectionId: string,
    data: Partial<ReflectionRecord>,
  ): Promise<ApiResponse<ReflectionRecord>> {
    return this.client.put<ReflectionRecord>(
      `/v1/cognition/reflections/${reflectionId}`,
      data,
    );
  }

  /** 删除反思记录 */
  async removeReflection(reflectionId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/cognition/reflections/${reflectionId}`);
  }

  // ==================== Growth 成长 ====================

  /** 列出成长记录（按 agentId 过滤，支持分页） */
  async listGrowths(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<GrowthRecord>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<GrowthRecord>>('/v1/cognition/growths', query);
  }

  /** 获取单条成长记录 */
  async getGrowth(growthId: string): Promise<ApiResponse<GrowthRecord>> {
    return this.client.get<GrowthRecord>(`/v1/cognition/growths/${growthId}`);
  }

  /** 创建成长记录 */
  async createGrowth(data: Partial<GrowthRecord>): Promise<ApiResponse<GrowthRecord>> {
    return this.client.post<GrowthRecord>('/v1/cognition/growths', data);
  }

  /** 更新成长记录 */
  async updateGrowth(
    growthId: string,
    data: Partial<GrowthRecord>,
  ): Promise<ApiResponse<GrowthRecord>> {
    return this.client.put<GrowthRecord>(`/v1/cognition/growths/${growthId}`, data);
  }

  /** 删除成长记录 */
  async removeGrowth(growthId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/cognition/growths/${growthId}`);
  }
}

/**
 * CognitionApi - 认知层 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   experience_knowledge_api.py @ /v1/experience：
 *     GET  /ranking?agent_id=&page=&size=   经验分页（契约投影：id/agent_id/
 *         task_type/skill_name/context/outcome/success_rate/proficiency/
 *         experience_count/lessons/adoption_outcome）
 *     DELETE /experience/{record_id}
 *   metacognition_api.py @ /v1/metacognition：
 *     GET /{agent_id}/metacognition?type=&page=&size=  元认知台账（thought 条目：
 *         {id,kind,type,content,context,confidence,metadata,created_at}）
 *     GET /{agent_id}/metacognition/history            反思时间线
 *   growth.py @ /v1/growth：
 *     GET /growth?agent_id=                 成长数据（motivation_level/personality/
 *         traits/values/constitution/questions...）
 *     GET|POST /reflection?agent_id=        反思日志（{created_at,confidence,
 *         trigger,summary} 列表）
 * 旧 /cognition/* 端点后端不存在，全部退役；零调用方法一并删除。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 经验条目（experience_knowledge_api._to_contract 契约投影，逐字段对齐） */
export interface ExperienceDto {
  id: string;
  agent_id: string;
  task_type: string;
  skill_name: string;
  context: string;
  outcome: string;
  success_rate: number | null;
  proficiency: number | null;
  experience_count: number;
  lessons: string[];
  adoption_outcome: string | null;
  evidence_state: string | null;
  injected_count: number | null;
  seen_count: number | null;
  operator_disposition: string | null;
  metadata: Record<string, Object>;
  created_at: string;
  updated_at: string;
}

/** 经验分页载荷 */
export interface ExperiencePage {
  items: ExperienceDto[];
  total: number;
  page: number;
  size: number;
}

/** 元认知台账条目（metacognition_api list_records 投影） */
export interface MetacognitionDto {
  id: number;
  kind: string;
  type: string;
  content: string;
  context: string;
  confidence: number;
  metadata: Record<string, Object>;
  created_at: string;
}

/** 元认知分页载荷 */
export interface MetacognitionPage {
  items: MetacognitionDto[];
  total: number;
  page: number;
  size: number;
}

/** 反思日志条目（growth.py _reflection_entry_to_item 投影，逐字段对齐） */
export interface ReflectionDto {
  log_id: string;
  agent_id: string;
  timestamp: number;
  reflection_type: string;
  content: string;
  insights: string[];
  confidence: number;
  related_memories: string[];
  status: string;
}

/** 反思日志创建请求（growth.py ReflectionLogCreate 契约） */
export interface ReflectionCreateRequest {
  reflection_type: string;
  content: string;
  insights: string[];
  confidence: number;
  related_memories: string[];
}

/** 人格画像（growth.py get_agent_growth 的 personality 子对象） */
export interface PersonalityDto {
  traits: Record<string, Object>;
  values: string[];
  communication_style: string;
  decision_style: string;
}

/** 宪法条目（constitution_persistence ConstitutionRule 投影） */
export interface ConstitutionRuleDto {
  rule_id: string;
  agent_id: string;
  timestamp: number;
  rule_type: string;
  content: string;
  priority: number;
  enabled: boolean;
}

/** 成长数据载荷（growth.py get_agent_growth，逐字段对齐） */
export interface GrowthDataDto {
  agent_id: string;
  timestamp: number;
  motivation_level: Record<string, Object> | null;
  personality: PersonalityDto | null;
  constitution: ConstitutionRuleDto[];
  reflection_logs: ReflectionDto[];
  questions: Object[];
  proactive_actions: Object[];
}

/** 知识图谱节点（knowledge_graph_api._node_to_dict 投影） */
export interface GraphNodeDto {
  id: string;
  label: string;
  type: string;
  description: string;
  weight: number;
  created_at: string | null;
}

/** 知识图谱边（knowledge_graph_api._edge_to_dict 投影） */
export interface GraphEdgeDto {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

/** 知识图谱载荷（knowledge_graph_api get_knowledge_graph data 投影，含真总量） */
export interface KnowledgeGraphDto {
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
  stats: Record<string, Object>;
  is_demo: boolean;
  hint: string;
}

export class CognitionApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  // ==================== Experience 经验 ====================

  /** 经验分页列表（/experience/ranking，按 skill_name 维度聚合投影） */
  async listExperiences(agentId: string, page: number, size: number): Promise<ApiResponse<ExperiencePage>> {
    const qs: string[] = [];
    if (agentId.length > 0) {
      qs.push('agent_id=' + encodeURIComponent(agentId));
    }
    qs.push('page=' + Math.max(page, 1).toString());
    qs.push('size=' + Math.min(Math.max(size, 1), 100).toString());
    return this.client.get<ExperiencePage>('/experience/ranking?' + qs.join('&'));
  }

  /** 删除经验记录 */
  async removeExperience(recordId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/experience/${recordId}`);
  }

  /** 手动结晶经验（POST /experience/records，AddExperienceRecordRequest 契约） */
  async createExperience(data: Record<string, Object>): Promise<ApiResponse<ExperienceDto>> {
    return this.client.post<ExperienceDto>('/experience/records', data);
  }

  // ==================== Metacognition 元认知 ====================

  /** 元认知台账（thought 条目，分页） */
  async listMetacognitions(agentId: string, page: number, size: number): Promise<ApiResponse<MetacognitionPage>> {
    const qs: string[] = [];
    qs.push('page=' + Math.max(page, 1).toString());
    qs.push('size=' + Math.min(Math.max(size, 1), 100).toString());
    return this.client.get<MetacognitionPage>(`/metacognition/${agentId}/metacognition?` + qs.join('&'));
  }

  /** 创建元认知记录（POST /metacognition/{agent_id}/metacognition，MetacognitionRecordCreate 契约） */
  async createMetacognition(agentId: string, data: Record<string, Object>): Promise<ApiResponse<MetacognitionDto>> {
    const aid = agentId.length > 0 ? agentId : 'default';
    return this.client.post<MetacognitionDto>(`/metacognition/${encodeURIComponent(aid)}/metacognition`, data);
  }

  // ==================== Reflection 反思 ====================

  /** 反思日志（growth.py /reflection，envelope.data 为列表） */
  async listReflections(agentId: string, limit: number): Promise<ApiResponse<ReflectionDto[]>> {
    const qs: string[] = [];
    qs.push('agent_id=' + encodeURIComponent(agentId.length > 0 ? agentId : 'default'));
    qs.push('limit=' + Math.min(Math.max(limit, 1), 100).toString());
    return this.client.get<ReflectionDto[]>('/growth/reflection?' + qs.join('&'));
  }

  /** 创建反思日志（POST /growth/reflection?agent_id=，body 为 ReflectionLogCreate） */
  async createReflection(agentId: string, data: ReflectionCreateRequest): Promise<ApiResponse<ReflectionDto>> {
    const qs = 'agent_id=' + encodeURIComponent(agentId.length > 0 ? agentId : 'default');
    return this.client.post<ReflectionDto>('/growth/reflection?' + qs, data);
  }

  // ==================== Growth 成长 ====================

  /** 成长数据（motivation/personality/traits/values/constitution/questions） */
  async getGrowthData(agentId: string): Promise<ApiResponse<GrowthDataDto>> {
    const qs = 'agent_id=' + encodeURIComponent(agentId.length > 0 ? agentId : 'default');
    return this.client.get<GrowthDataDto>('/growth?' + qs);
  }

  // ==================== Knowledge Graph 知识图谱 ====================

  /** 知识图谱（GET /knowledge-graph/{agent_id}/knowledge-graph，裁剪子图+真总量） */
  async getKnowledgeGraph(agentId: string, limit?: number): Promise<ApiResponse<KnowledgeGraphDto>> {
    const capped = Math.min(Math.max(limit !== undefined ? limit : 100, 1), 500);
    const aid = agentId.length > 0 ? agentId : 'default';
    return this.client.get<KnowledgeGraphDto>(`/knowledge-graph/${encodeURIComponent(aid)}/knowledge-graph?limit=${capped}`);
  }
}

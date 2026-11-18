/**
 * AgentsApi - Agent API 模块（同源 PC，端点经 agent.py 源码核对 2026-11-16）
 *
 * 后端事实源：neurova/api/endpoints/agent.py（挂 /v1/agents）：
 *   GET    /agents        → **裸数组** List[AgentInfo]（Wave H-W0 属主过滤：admin 全量、
 *                            普通用户仅自有——按账号取现有 Agent 即本接口）
 *   GET    /agents/{id}   → 裸 AgentInfo
 *   POST   /agents        → CreateAgentRequest → 裸 AgentInfo
 *   PUT    /agents/{id}   → 裸 AgentInfo
 *   DELETE /agents/{id}
 * 字段映射：AgentInfo.agent_id → Agent.id；status 归一化到 AgentStatus。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse, Agent, AgentStatus } from '../../types';

/** 后端 AgentInfo 投影（agent.py） */
export interface AgentInfoDto {
  agent_id: string;
  name: string;
  description: string;
  model: string;
  provider: string;
  status: string;
  memory_enabled: boolean;
  tools_count: number;
  owner_user_id: string;
  /** 后端可空（实测回 null）——分组标识，归 AdminGroups 域，不再冒充 createdAt */
  group_id: string;
  /** 后端可空（agent.py:221）——Agent 创建时间，createdAt 的唯一事实源 */
  created_at: string;
}

export class AgentsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 后端 status → 前端 AgentStatus 归一化 */
  private static normStatus(status: string): AgentStatus {
    if (status === 'online' || status === 'running' || status === 'active') {
      return 'active';
    }
    if (status === 'sleeping') {
      return 'sleeping';
    }
    if (status === 'error') {
      return 'error';
    }
    return 'inactive';
  }

  /** AgentInfo → Agent 映射（单源）。后端可空字段（group_id/description/created_at 实测返回 null）在此兜底 */
  private static toAgent(dto: AgentInfoDto): Agent {
    const agent: Agent = {
      id: dto.agent_id,
      name: dto.name,
      description: dto.description ?? '',
      model: dto.model,
      provider: dto.provider,
      status: AgentsApi.normStatus(dto.status),
      createdAt: dto.created_at ?? '',
      updatedAt: '',
    };
    agent.toolsCount = dto.tools_count;
    return agent;
  }

  /** 列出 Agent（按登录账号过滤：admin 全量、普通用户仅自有） */
  async list(): Promise<Agent[]> {
    const res = await this.client.get<AgentInfoDto[]>('/agents');
    const arr = res as Object as AgentInfoDto[];
    const out: Agent[] = [];
    for (const dto of arr) {
      out.push(AgentsApi.toAgent(dto));
    }
    return out;
  }

  /** 单个 Agent 详情 */
  async get(agentId: string): Promise<Agent> {
    const res = await this.client.get<AgentInfoDto>(`/agents/${agentId}`);
    const dto = res as Object as AgentInfoDto;
    if (!dto || !dto.agent_id) {
      throw new Error('智能体不存在或无权访问');
    }
    return AgentsApi.toAgent(dto);
  }

  /** 创建 Agent */
  async create(data: Partial<Agent>): Promise<Agent> {
    const res = await this.client.post<Agent>('/agents', data);
    this.assertAgent(res);
    return res as Object as Agent;
  }

  /** 更新 Agent */
  async update(agentId: string, data: Partial<Agent>): Promise<Agent> {
    const res = await this.client.put<Agent>(`/agents/${agentId}`, data);
    this.assertAgent(res);
    return res as Object as Agent;
  }

  /** 删除 Agent */
  async remove(agentId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/agents/${agentId}`);
  }

  /** 后端错误响应（{detail:...}）直接抛出，成功（含 agent_id）原样返回 */
  private assertAgent(res: ApiResponse<Agent>): void {
    const rec = res as Object as Record<string, Object>;
    if (rec['detail'] !== undefined) {
      const detail = rec['detail'];
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
  }
}

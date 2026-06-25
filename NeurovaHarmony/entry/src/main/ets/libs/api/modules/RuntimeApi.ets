/**
 * RuntimeApi - 运行时层 API 模块
 *
 * 职责：封装运行时资源（调度任务/上下文消息/计算机任务/追踪/轨迹/休眠状态/防火墙）的操作
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 覆盖实体：
 *   - ScheduleTask    调度任务（CRUD）
 *   - ContextMessage  上下文消息（list/get/remove，无 create/update）
 *   - ComputerTask    计算机任务（list/get/create/remove，无 update）
 *   - TraceEntry      追踪条目（list/get/remove，只读）
 *   - TrajectoryPoint 轨迹点（list/get，只读）
 *   - SleepStatus     休眠状态（get/setMode/awaken，特殊单例）
 *   - FirewallRule    防火墙规则（CRUD）
 *
 * 用法：
 *   const api = ApiFacade.getInstance().runtime;
 *   const page = await api.listScheduleTasks('agent-1', { page: 1, size: 20 });
 *   const sleep = await api.getSleepStatus('agent-1');
 *   await api.awaken('agent-1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  PageParams,
  PageResult,
  ScheduleTask,
  ContextMessage,
  ComputerTask,
  TraceEntry,
  TrajectoryPoint,
  SleepStatus,
  FirewallRule,
} from '../../types';

export class RuntimeApi {
  constructor(private client: HttpClient) {}

  // ==================== ScheduleTask 调度任务 ====================

  /** 列出调度任务（按 agentId 过滤，支持分页） */
  async listScheduleTasks(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ScheduleTask>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<ScheduleTask>>('/v1/runtime/scheduler', query);
  }

  /** 获取单条调度任务 */
  async getScheduleTask(taskId: string): Promise<ApiResponse<ScheduleTask>> {
    return this.client.get<ScheduleTask>(`/v1/runtime/scheduler/${taskId}`);
  }

  /** 创建调度任务 */
  async createScheduleTask(data: Partial<ScheduleTask>): Promise<ApiResponse<ScheduleTask>> {
    return this.client.post<ScheduleTask>('/v1/runtime/scheduler', data);
  }

  /** 更新调度任务 */
  async updateScheduleTask(
    taskId: string,
    data: Partial<ScheduleTask>,
  ): Promise<ApiResponse<ScheduleTask>> {
    return this.client.put<ScheduleTask>(`/v1/runtime/scheduler/${taskId}`, data);
  }

  /** 删除调度任务 */
  async removeScheduleTask(taskId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/runtime/scheduler/${taskId}`);
  }

  // ==================== ContextMessage 上下文消息 ====================

  /** 列出上下文消息（按 sessionId 过滤，支持分页） */
  async listContextMessages(
    sessionId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ContextMessage>>> {
    const query: Record<string, Object> = { sessionId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<ContextMessage>>('/v1/runtime/context', query);
  }

  /** 获取单条上下文消息 */
  async getContextMessage(messageId: string): Promise<ApiResponse<ContextMessage>> {
    return this.client.get<ContextMessage>(`/v1/runtime/context/${messageId}`);
  }

  /** 删除上下文消息 */
  async removeContextMessage(messageId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/runtime/context/${messageId}`);
  }

  // ==================== ComputerTask 计算机任务 ====================

  /** 列出计算机任务（按 agentId 过滤，支持分页） */
  async listComputerTasks(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ComputerTask>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<ComputerTask>>('/v1/runtime/computer', query);
  }

  /** 获取单条计算机任务 */
  async getComputerTask(taskId: string): Promise<ApiResponse<ComputerTask>> {
    return this.client.get<ComputerTask>(`/v1/runtime/computer/${taskId}`);
  }

  /** 创建计算机任务 */
  async createComputerTask(data: Partial<ComputerTask>): Promise<ApiResponse<ComputerTask>> {
    return this.client.post<ComputerTask>('/v1/runtime/computer', data);
  }

  /** 删除计算机任务 */
  async removeComputerTask(taskId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/runtime/computer/${taskId}`);
  }

  // ==================== TraceEntry 追踪条目 ====================

  /** 列出追踪条目（按 agentId 过滤，支持分页） */
  async listTraces(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<TraceEntry>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<TraceEntry>>('/v1/runtime/traces', query);
  }

  /** 获取单条追踪条目 */
  async getTrace(traceId: string): Promise<ApiResponse<TraceEntry>> {
    return this.client.get<TraceEntry>(`/v1/runtime/traces/${traceId}`);
  }

  /** 删除追踪条目 */
  async removeTrace(traceId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/runtime/traces/${traceId}`);
  }

  // ==================== TrajectoryPoint 轨迹点 ====================

  /** 列出轨迹点（按 agentId 过滤，支持分页） */
  async listTrajectory(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<TrajectoryPoint>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<TrajectoryPoint>>('/v1/runtime/trajectory', query);
  }

  /** 获取单条轨迹点 */
  async getTrajectoryPoint(pointId: string): Promise<ApiResponse<TrajectoryPoint>> {
    return this.client.get<TrajectoryPoint>(`/v1/runtime/trajectory/${pointId}`);
  }

  // ==================== SleepStatus 休眠状态 ====================

  /** 获取 Agent 的休眠状态 */
  async getSleepStatus(agentId: string): Promise<ApiResponse<SleepStatus>> {
    return this.client.get<SleepStatus>('/v1/runtime/sleep', { agentId });
  }

  /** 设置休眠模式（body: { agentId, mode }） */
  async setSleepMode(agentId: string, mode: 'idle' | 'light' | 'deep'): Promise<ApiResponse<SleepStatus>> {
    return this.client.post<SleepStatus>('/v1/runtime/sleep', { agentId, mode });
  }

  /** 唤醒 Agent（body: { agentId }） */
  async awaken(agentId: string): Promise<ApiResponse<SleepStatus>> {
    return this.client.post<SleepStatus>('/v1/runtime/sleep/awaken', { agentId });
  }

  // ==================== FirewallRule 防火墙规则 ====================

  /** 列出防火墙规则（按 agentId 过滤，支持分页） */
  async listFirewallRules(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<FirewallRule>>> {
    const query: Record<string, Object> = { agentId };
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<FirewallRule>>('/v1/runtime/firewall', query);
  }

  /** 获取单条防火墙规则 */
  async getFirewallRule(ruleId: string): Promise<ApiResponse<FirewallRule>> {
    return this.client.get<FirewallRule>(`/v1/runtime/firewall/${ruleId}`);
  }

  /** 创建防火墙规则 */
  async createFirewallRule(data: Partial<FirewallRule>): Promise<ApiResponse<FirewallRule>> {
    return this.client.post<FirewallRule>('/v1/runtime/firewall', data);
  }

  /** 更新防火墙规则 */
  async updateFirewallRule(
    ruleId: string,
    data: Partial<FirewallRule>,
  ): Promise<ApiResponse<FirewallRule>> {
    return this.client.put<FirewallRule>(`/v1/runtime/firewall/${ruleId}`, data);
  }

  /** 删除防火墙规则 */
  async removeFirewallRule(ruleId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/runtime/firewall/${ruleId}`);
  }
}

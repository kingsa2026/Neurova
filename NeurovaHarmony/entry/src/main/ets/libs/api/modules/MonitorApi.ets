/**
 * MonitorApi - 监控管理 + NEURON API 模块
 *
 * 职责：封装监控域 6 个实体的操作：
 *   Stat（统计）、MonitorMetric（指标）、LogEntry（日志）、
 *   NotificationItem（通知）、FileItem（文件）、Neuron（神经元）
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().monitor;
 *   const stats = await api.listStats('day');
 *   await api.pushMetric({ name: 'cpu', value: 0.4, unit: 'ratio', timestamp: now });
 *   await api.fireNeuron('n1');
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  Stat,
  MonitorMetric,
  LogEntry,
  LogLevel,
  NotificationItem,
  FileItem,
  Neuron,
  PageResult,
  PageParams,
} from '../../types';

export class MonitorApi {
  constructor(private client: HttpClient) {}

  // ========== Stat（统计指标）==========

  /** 列出统计指标（可选周期过滤） */
  async listStats(period?: string): Promise<ApiResponse<Stat[]>> {
    const query: Record<string, Object> = {};
    if (period) query['period'] = period;
    return this.client.get<Stat[]>('/v1/monitor/stats', query);
  }

  /** 获取单个统计指标 */
  async getStat(key: string): Promise<ApiResponse<Stat>> {
    return this.client.get<Stat>(`/v1/monitor/stats/${key}`);
  }

  // ========== MonitorMetric（监控指标）==========

  /** 列出监控指标（可选 name 过滤 + 分页） */
  async listMetrics(
    name?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<MonitorMetric>>> {
    const query: Record<string, Object> = {};
    if (name) query['name'] = name;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<MonitorMetric>>('/v1/monitor/metrics', query);
  }

  /** 推送监控指标 */
  async pushMetric(data: Partial<MonitorMetric>): Promise<ApiResponse<MonitorMetric>> {
    return this.client.post<MonitorMetric>('/v1/monitor/metrics', data);
  }

  // ========== LogEntry（日志）==========

  /** 列出日志（可选 level / source 过滤 + 分页） */
  async listLogs(
    params?: PageParams,
    level?: LogLevel,
    source?: string,
  ): Promise<ApiResponse<PageResult<LogEntry>>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    if (level) query['level'] = level;
    if (source) query['source'] = source;
    return this.client.get<PageResult<LogEntry>>('/v1/monitor/logs', query);
  }

  /** 获取单条日志 */
  async getLog(id: string): Promise<ApiResponse<LogEntry>> {
    return this.client.get<LogEntry>(`/v1/monitor/logs/${id}`);
  }

  /** 删除单条日志 */
  async removeLog(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/monitor/logs/${id}`);
  }

  /** 清理日志（可选 before 时间点，body 传递） */
  async clearLogs(before?: string): Promise<ApiResponse<Object>> {
    const body: { before?: string } = {};
    if (before !== undefined) body.before = before;
    return this.client.post<Object>('/v1/monitor/logs/clear', body);
  }

  // ========== NotificationItem（通知）==========

  /** 列出通知（可选仅未读过滤） */
  async listNotifications(unreadOnly?: boolean): Promise<ApiResponse<NotificationItem[]>> {
    const query: Record<string, Object> = {};
    if (unreadOnly !== undefined) query['unreadOnly'] = unreadOnly;
    return this.client.get<NotificationItem[]>('/v1/monitor/notifications', query);
  }

  /** 获取单条通知 */
  async getNotification(id: string): Promise<ApiResponse<NotificationItem>> {
    return this.client.get<NotificationItem>(`/v1/monitor/notifications/${id}`);
  }

  /** 标记单条通知为已读 */
  async markNotificationRead(id: string): Promise<ApiResponse<Object>> {
    return this.client.post<Object>(`/v1/monitor/notifications/${id}/read`, {});
  }

  /** 标记所有通知为已读 */
  async markAllNotificationsRead(): Promise<ApiResponse<Object>> {
    return this.client.post<Object>('/v1/monitor/notifications/read-all', {});
  }

  /** 删除单条通知 */
  async removeNotification(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/monitor/notifications/${id}`);
  }

  // ========== FileItem（文件）==========

  /** 列出文件（可选 parentId 过滤 + 分页） */
  async listFiles(
    parentId?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<FileItem>>> {
    const query: Record<string, Object> = {};
    if (parentId) query['parentId'] = parentId;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<FileItem>>('/v1/monitor/files', query);
  }

  /** 获取单条文件项 */
  async getFile(id: string): Promise<ApiResponse<FileItem>> {
    return this.client.get<FileItem>(`/v1/monitor/files/${id}`);
  }

  /** 创建文件夹 */
  async createFolder(data: Partial<FileItem>): Promise<ApiResponse<FileItem>> {
    return this.client.post<FileItem>('/v1/monitor/files/folder', data);
  }

  /** 上传文件 */
  async uploadFile(data: Partial<FileItem>): Promise<ApiResponse<FileItem>> {
    return this.client.post<FileItem>('/v1/monitor/files', data);
  }

  /** 删除文件项 */
  async removeFile(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/monitor/files/${id}`);
  }

  // ========== Neuron（神经元）==========

  /** 列出神经元（可选 agentId 过滤 + 分页） */
  async listNeurons(
    agentId?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Neuron>>> {
    const query: Record<string, Object> = {};
    if (agentId) query['agentId'] = agentId;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Neuron>>('/v1/monitor/neurons', query);
  }

  /** 获取单个神经元 */
  async getNeuron(id: string): Promise<ApiResponse<Neuron>> {
    return this.client.get<Neuron>(`/v1/monitor/neurons/${id}`);
  }

  /** 更新神经元 */
  async updateNeuron(id: string, data: Partial<Neuron>): Promise<ApiResponse<Neuron>> {
    return this.client.put<Neuron>(`/v1/monitor/neurons/${id}`, data);
  }

  /** 触发神经元放电 */
  async fireNeuron(id: string): Promise<ApiResponse<Neuron>> {
    return this.client.post<Neuron>(`/v1/monitor/neurons/${id}/fire`, {});
  }
}

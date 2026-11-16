/**
 * MonitorApi - 监控域 + NEURON + 通知 + 文件 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   monitor.py @ /v1/monitor（admin 门控）：
 *     GET /status     → {status,uptime,version,python_version,start_time}
 *     GET /resources  → {cpu|memory|disk: {usage,trend,history,used,total}}
 *     GET /connections → [{name,detail,status}]
 *     GET /alerts?level=&resolved=&limit= → [{id,severity,title,message,source,timestamp,resolved}]
 *     POST /alerts/{alert_id}/resolve
 *   neuron.py @ /v1/neuron（模块自述前缀）：
 *     GET  /entities?entity_type=&limit= → {success,data:[{id,name,entity_type,metadata,...}],total}
 *     POST /entities {name,entity_type,metadata}
 *     GET  /stats  → {success,data:{total_entities,total_edges,entity_types,dependency_types}}
 *     GET  /health → {success,status,components}
 *   notifications.py @ /v1/notifications：GET ""（data={items,total}）、POST /{id}/read、
 *     POST /mark-all-read、DELETE /{id}、GET /unread-count
 *   files_api.py @ /v1/files：GET ""（裸数组）、GET/PUT/DELETE /{file_id}
 * 旧 /monitor/stats|metrics|logs|neurons 与 /monitor/neurons/{id}/fire 后端不存在：
 * 对应方法一律 throw 点名（页面 catch 透出原因），不再发往不存在的路由。
 */

import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  NotificationItem,
  FileItem,
  PageResult,
  PageParams,
  Stat,
  MonitorMetric,
  LogEntry,
  LogLevel,
  Neuron,
} from '../../types';

/** 系统状态（monitor.get_system_status） */
export interface SystemStatusDto {
  status: string;
  uptime: number;
  version: string;
  python_version: string;
  start_time: number;
}

/** 单资源快照（monitor.ResourceSnapshot） */
export interface ResourceSnapshotDto {
  usage: number;
  trend: number;
  history: number[];
  used: number;
  total: number;
}

/** 资源使用（monitor.ResourceUsage：cpu/memory/disk 各为对象） */
export interface ResourceUsageDto {
  cpu: ResourceSnapshotDto;
  memory: ResourceSnapshotDto;
  disk: ResourceSnapshotDto;
}

/** 连接状态（monitor.ConnectionStatus） */
export interface ConnectionStatusDto {
  name: string;
  detail: string;
  status: string;
}

/** 告警条目（monitor.get_alerts 投影） */
export interface AlertDto {
  id: string;
  severity: string;
  title: string;
  message: string;
  source: string;
  timestamp: number;
  resolved: boolean;
}

/** NEURON 实体（dependency_graph.EntityNode 投影） */
export interface NeuronEntityDto {
  id: string;
  name: string;
  entity_type: string;
  metadata: Record<string, Object>;
  created_at: number;
  updated_at: number;
}

/** NEURON 统计（neuron.get_neuron_stats data 投影） */
export interface NeuronStatsDto {
  total_entities: number;
  total_edges: number;
  entity_types: number;
  dependency_types: number;
}

/** 清理日志 body（before 为可选截止时间点；后端无此端点，仅存类型） */
interface ClearLogsBody {
  before?: string;
}

export class MonitorApi {
  private client: HttpClient;
  constructor(client: HttpClient) {
    this.client = client;
  }

  // ========== 系统状态 / 资源 / 连接 / 告警（真实端点，admin 门控）==========

  /** 系统状态（GET /monitor/status，需管理员） */
  async getSystemStatus(): Promise<ApiResponse<SystemStatusDto>> {
    return this.client.get<SystemStatusDto>('/monitor/status');
  }

  /** 资源使用（GET /monitor/resources，psutil 真值 + 滚动历史，需管理员） */
  async getResources(): Promise<ApiResponse<ResourceUsageDto>> {
    return this.client.get<ResourceUsageDto>('/monitor/resources');
  }

  /** 连接状态汇总（GET /monitor/connections：providers/agents/db/执行监控，需管理员） */
  async listConnections(): Promise<ApiResponse<ConnectionStatusDto[]>> {
    return this.client.get<ConnectionStatusDto[]>('/monitor/connections');
  }

  /** 告警列表（GET /monitor/alerts，ExecutionMonitor 真实告警，需管理员） */
  async listAlerts(level?: string, resolved?: boolean, limit?: number): Promise<ApiResponse<AlertDto[]>> {
    const query: Record<string, Object> = {};
    if (level !== undefined && level.length > 0) query['level'] = level;
    if (resolved !== undefined) query['resolved'] = resolved;
    if (limit !== undefined) query['limit'] = limit;
    return this.client.get<AlertDto[]>('/monitor/alerts', query);
  }

  /** 解决告警（POST /monitor/alerts/{alert_id}/resolve，acknowledge） */
  async resolveAlert(alertId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/monitor/alerts/${alertId}/resolve`, body);
  }

  // ========== Stat / Metric / Log（后端无此端点，保留原签名抛错点名）==========

  /** @deprecated 后端无 GET /monitor/stats（真实面为 status/resources/connections/alerts） */
  async listStats(period?: string): Promise<ApiResponse<Stat[]>> {
    throw new Error('后端无此端点：GET /v1/monitor/stats（监控域实际提供 status/resources/connections/alerts）');
  }

  /** @deprecated 后端无 GET /monitor/stats/{key} */
  async getStat(key: string): Promise<ApiResponse<Stat>> {
    throw new Error('后端无此端点：GET /v1/monitor/stats/{key}');
  }

  /** @deprecated 后端无 GET /monitor/metrics */
  async listMetrics(name?: string, params?: PageParams): Promise<ApiResponse<PageResult<MonitorMetric>>> {
    throw new Error('后端无此端点：GET /v1/monitor/metrics（监控域实际提供 status/resources/connections/alerts）');
  }

  /** @deprecated 后端无 POST /monitor/metrics */
  async pushMetric(data: Partial<MonitorMetric>): Promise<ApiResponse<MonitorMetric>> {
    throw new Error('后端无此端点：POST /v1/monitor/metrics');
  }

  /** @deprecated 后端无 GET /monitor/logs（日志面暂未暴露 REST 端点） */
  async listLogs(params?: PageParams, level?: LogLevel, source?: string): Promise<ApiResponse<PageResult<LogEntry>>> {
    throw new Error('后端无此端点：GET /v1/monitor/logs');
  }

  /** @deprecated 后端无 GET /monitor/logs/{id} */
  async getLog(id: string): Promise<ApiResponse<LogEntry>> {
    throw new Error('后端无此端点：GET /v1/monitor/logs/{id}');
  }

  /** @deprecated 后端无 DELETE /monitor/logs/{id} */
  async removeLog(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/monitor/logs/{id}');
  }

  /** @deprecated 后端无 POST /monitor/logs/clear */
  async clearLogs(before?: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：POST /v1/monitor/logs/clear');
  }

  // ========== NotificationItem（通知，真实端点）==========

  /** 列出通知（后端信封 data={items,total}，这里拆包回数组） */
  async listNotifications(unreadOnly?: boolean): Promise<ApiResponse<NotificationItem[]>> {
    const query: Record<string, Object> = {};
    if (unreadOnly !== undefined) query['read'] = !unreadOnly;
    const res = await this.client.get<PageResult<NotificationItem>>('/notifications', query);
    const page = (res.data ?? { items: [], total: 0 }) as PageResult<NotificationItem>;
    return { code: res.code, message: res.message, data: page.items } as ApiResponse<NotificationItem[]>;
  }

  /** 未读计数（GET /notifications/unread-count） */
  async getUnreadCount(): Promise<ApiResponse<number>> {
    return this.client.get<number>('/notifications/unread-count');
  }

  /** 标记单条通知为已读 */
  async markNotificationRead(id: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/notifications/${id}/read`, body);
  }

  /** 标记所有通知为已读 */
  async markAllNotificationsRead(): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>('/notifications/mark-all-read', body);
  }

  /** 删除单条通知 */
  async removeNotification(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/notifications/${id}`);
  }

  /** @deprecated 后端无 GET /notifications/{id} */
  async getNotification(id: string): Promise<ApiResponse<NotificationItem>> {
    throw new Error('后端无此端点：GET /v1/notifications/{id}（列表即全量）');
  }

  // ========== FileItem（文件，真实端点）==========

  /** 列出文件（GET /files 返回裸数组，这里包成 PageResult；后端暂无目录层级，parentId 仅保留签名） */
  async listFiles(
    parentId?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<FileItem>>> {
    const res = await this.client.get<FileItem[]>('/files');
    const arr = (res.data ?? []) as FileItem[];
    return {
      code: 0, message: 'ok',
      data: { items: arr, total: arr.length, page: 1, size: arr.length },
    } as ApiResponse<PageResult<FileItem>>;
  }

  /** 获取单条文件项 */
  async getFile(id: string): Promise<ApiResponse<FileItem>> {
    return this.client.get<FileItem>(`/files/${id}`);
  }

  /** 更新文件项 */
  async updateFile(id: string, data: Object): Promise<ApiResponse<FileItem>> {
    return this.client.put<FileItem>(`/files/${id}`, data);
  }

  /** 删除文件项 */
  async removeFile(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/files/${id}`);
  }

  // ========== NEURON 实体（真实端点 /neuron/*）==========

  /** NEURON 实体列表（GET /neuron/entities?entity_type=&limit=，信封 {success,data,total}，这里拆包回数组） */
  async listNeurons(entityType?: string, params?: PageParams): Promise<ApiResponse<NeuronEntityDto[]>> {
    const query: Record<string, Object> = {};
    if (entityType !== undefined && entityType.length > 0) query['entity_type'] = entityType;
    if (params && params.page !== undefined) query['page'] = params.page;
    if (params && params.size !== undefined) query['limit'] = params.size;
    const res = await this.client.get<Object>('/neuron/entities', query);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const items = (payload['data'] ?? []) as NeuronEntityDto[];
    return { code: res.code, message: res.message, data: items } as ApiResponse<NeuronEntityDto[]>;
  }

  /** 创建 NEURON 实体（POST /neuron/entities {name,entity_type,metadata}） */
  async createNeuronEntity(name: string, entityType: string, metadata: Record<string, Object>): Promise<ApiResponse<NeuronEntityDto>> {
    const body: Record<string, Object> = {
      'name': name,
      'entity_type': entityType,
      'metadata': metadata,
    };
    return this.client.post<NeuronEntityDto>('/neuron/entities', body);
  }

  /** NEURON 统计（GET /neuron/stats，信封 {success,data}，这里拆包回 data） */
  async getNeuronStats(): Promise<ApiResponse<NeuronStatsDto>> {
    const res = await this.client.get<Object>('/neuron/stats');
    const payload = (res.data ?? {}) as Record<string, Object>;
    const stats = (payload['data'] ?? {}) as NeuronStatsDto;
    return { code: res.code, message: res.message, data: stats } as ApiResponse<NeuronStatsDto>;
  }

  /** NEURON 健康检查（GET /neuron/health） */
  async getNeuronHealth(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/neuron/health');
  }

  /** @deprecated 后端无 GET /monitor/neurons/{id}（实体详情只有列表面） */
  async getNeuron(id: string): Promise<ApiResponse<Neuron>> {
    throw new Error('后端无此端点：GET /v1/monitor/neurons/{id}（NEURON 实际为 /v1/neuron/entities 列表）');
  }

  /** @deprecated 后端无 PUT /monitor/neurons/{id} */
  async updateNeuron(id: string, data: Partial<Neuron>): Promise<ApiResponse<Neuron>> {
    throw new Error('后端无此端点：PUT /v1/monitor/neurons/{id}');
  }

  /** @deprecated 后端无 POST /monitor/neurons/{id}/fire（NEURON 实际提供 cascade/would-affect 等推理端点） */
  async fireNeuron(id: string): Promise<ApiResponse<Neuron>> {
    throw new Error('后端无此端点：POST /v1/monitor/neurons/{id}/fire');
  }
}

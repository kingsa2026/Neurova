/**
 * MonitorApi - 监控域 + NEURON + 通知 + 文件 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   monitor.py @ /v1/monitor（admin 门控）：
 *     GET /status     → SystemStatus（裸对象，边界归一）
 *     GET /resources  → {cpu|memory|disk: {usage,trend,history,used,total}}（裸对象）
 *     GET /connections → [{name,detail,status}]（裸数组）
 *     GET /alerts?level=&resolved=&limit= → [{id,severity,...}]（裸数组）
 *     POST /alerts/{alert_id}/resolve → {code,message}
 *   stats.py @ /v1/stats：GET "" → {overview,trends}（裸对象；P1-35 接线为 listStats）
 *   logs.py @ /v1/logs：GET "" → [LogEntry]（裸数组；P1-35 接线为 listLogs）、
 *     DELETE ""（清空；接线为 clearLogs）、POST /search、GET /levels
 *   neuron.py 自述 prefix="/neuron" 挂 /api/neuron（**无 /v1**，P1-30）：
 *     GET  /entities?entity_type=&limit= → {success,data:[...],total}
 *     POST /entities {name,entity_type,metadata} → {success,data}
 *     GET  /stats  → {success,data:{...}}
 *     GET  /health → {success,status,components}
 *   notifications.py @ /v1/notifications：GET ""（data={items,total}）、POST /{id}/read、
 *     POST /mark-all-read、DELETE /{id}、GET /unread-count
 *   files_api.py @ /v1/files：GET ""（裸数组）、GET/PUT/DELETE /{file_id}
 * 后端无 /monitor/metrics、/monitor/logs/{id} 等：对应方法一律 throw 点名
 * （页面 catch 透出原因），不发往不存在的路由。
 */

import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList, asEnvelopeSuccessData } from '../envelope';
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

  // ========== 系统状态 / 资源 / 连接 / 告警（真实端点，admin 门控；裸形状边界归一）==========

  /** 系统状态（GET /monitor/status，SystemStatus 裸对象边界归一，需管理员） */
  async getSystemStatus(): Promise<ApiResponse<SystemStatusDto>> {
    const res = await this.client.get<SystemStatusDto>('/monitor/status');
    return asEnvelope<SystemStatusDto>(res, ['status', 'uptime', 'version']);
  }

  /** 资源使用（GET /monitor/resources，psutil 真值 + 滚动历史，ResourceUsage 裸对象边界归一，需管理员） */
  async getResources(): Promise<ApiResponse<ResourceUsageDto>> {
    const res = await this.client.get<ResourceUsageDto>('/monitor/resources');
    return asEnvelope<ResourceUsageDto>(res, ['cpu', 'memory', 'disk']);
  }

  /** 连接状态汇总（GET /monitor/connections：providers/agents/db/执行监控，裸数组边界归一，需管理员） */
  async listConnections(): Promise<ApiResponse<ConnectionStatusDto[]>> {
    const res = await this.client.get<ConnectionStatusDto[]>('/monitor/connections');
    return asEnvelopeList<ConnectionStatusDto>(res as ApiResponse<ConnectionStatusDto[]>);
  }

  /** 告警列表（GET /monitor/alerts，ExecutionMonitor 真实告警，裸数组边界归一，需管理员） */
  async listAlerts(level?: string, resolved?: boolean, limit?: number): Promise<ApiResponse<AlertDto[]>> {
    const query: Record<string, Object> = {};
    if (level !== undefined && level.length > 0) query['level'] = level;
    if (resolved !== undefined) query['resolved'] = resolved;
    if (limit !== undefined) query['limit'] = limit;
    const res = await this.client.get<AlertDto[]>('/monitor/alerts', query);
    return asEnvelopeList<AlertDto>(res as ApiResponse<AlertDto[]>);
  }

  /** 解决告警（POST /monitor/alerts/{alert_id}/resolve，acknowledge；后端返 {code,message} 信封） */
  async resolveAlert(alertId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/monitor/alerts/${alertId}/resolve`, body);
  }

  // ========== Stat / Metric / Log（P1-35 接线：logs→/v1/logs、stats→/v1/stats）==========

  /** 后端日志级别词汇 → 前端 LogLevel（WARNING→warn、CRITICAL→fatal） */
  private static normLogLevel(level: string): LogLevel {
    const l = level.toLowerCase();
    if (l === 'warning') return 'warn';
    if (l === 'critical' || l === 'fatal') return 'fatal';
    if (l === 'debug' || l === 'info' || l === 'error') return l as LogLevel;
    return 'info';
  }

  /** 秒级时间戳 → ISO 字符串（空值/0 回退 ''） */
  private static tsToIso(ts: number | null | undefined): string {
    if (ts === null || ts === undefined || ts <= 0) return '';
    return new Date(ts * 1000).toISOString();
  }

  /** 后端 logs.py LogEntry → 前端 LogEntry（单源映射） */
  private static toLogEntry(dto: Record<string, Object>): LogEntry {
    const entry: LogEntry = {
      id: String(dto['log_id'] ?? ''),
      level: MonitorApi.normLogLevel(String(dto['level'] ?? 'info')),
      source: String(dto['source'] ?? ''),
      message: String(dto['message'] ?? ''),
      timestamp: MonitorApi.tsToIso(Number(dto['timestamp'] ?? 0)),
    };
    return entry;
  }

  /**
   * 列出日志（P1-35 接线：GET /v1/logs，后端裸数组边界归一后本地分页）
   * 后端 limit 上限 1000；level/source 直传后端过滤。
   */
  async listLogs(params?: PageParams, level?: LogLevel, source?: string): Promise<ApiResponse<PageResult<LogEntry>>> {
    const query: Record<string, Object> = {};
    if (level !== undefined && level.length > 0) query['level'] = level;
    if (source !== undefined && source.length > 0) query['source'] = source;
    if (params && params.size !== undefined) query['limit'] = params.size;
    if (params && params.page !== undefined && params.size !== undefined) {
      query['offset'] = (Math.max(params.page, 1) - 1) * params.size;
    }
    const res = asEnvelopeList<Record<string, Object>>(await this.client.get<Record<string, Object>[]>('/logs', query));
    const arr = (res.data ?? []) as Array<Record<string, Object>>;
    const items: LogEntry[] = [];
    for (const dto of arr) {
      items.push(MonitorApi.toLogEntry(dto));
    }
    const size = params && params.size !== undefined ? params.size : arr.length;
    const page = params && params.page !== undefined ? params.page : 1;
    const result: PageResult<LogEntry> = { items: items, total: items.length, page: page, size: size };
    return { code: res.code, message: res.message, data: result } as ApiResponse<PageResult<LogEntry>>;
  }

  /** @deprecated 后端无 GET /v1/logs/{id}（日志只有列表与搜索面） */
  async getLog(id: string): Promise<ApiResponse<LogEntry>> {
    throw new Error('后端无此端点：GET /v1/logs/{id}（日志面只有 GET /v1/logs 列表与 POST /v1/logs/search）');
  }

  /** @deprecated 后端无 DELETE /v1/logs/{id}（清空是整批 DELETE /v1/logs） */
  async removeLog(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/logs/{id}（清空日志走 clearLogs → DELETE /v1/logs）');
  }

  /** 清空日志（P1-35 接线：DELETE /v1/logs 整批清空；后端不支持按时间点 before 截断） */
  async clearLogs(before?: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>('/logs');
  }

  /** 后端 /v1/stats overview 键 → 前端中文标签（单源映射） */
  private static readonly STAT_LABELS: Record<string, string> = {
    'agents': '智能体数',
    'conversations': '会话数',
    'memories': '记忆数',
    'tokens': 'Token 用量',
    'api_calls': 'API 调用',
    'errors': '错误数',
    'uptime': '运行时长(秒)',
  };

  /**
   * 系统统计（P1-35 接线：GET /v1/stats 的 overview 真实计数 → Stat[]）
   * 后端不按 period 分桶（day/week/month 同一份全量 overview），period 仅保留签名。
   */
  async listStats(period?: string): Promise<ApiResponse<Stat[]>> {
    const res = asEnvelope<Object>(await this.client.get<Object>('/stats'), ['overview', 'trends']);
    if (res.code !== 0 || !res.data) {
      throw new Error(res.message && res.message.length > 0 ? res.message : '统计获取失败');
    }
    const overview = ((res.data as Record<string, Object>)['overview'] ?? {}) as Record<string, Object>;
    const stats: Stat[] = [];
    const now = new Date().toISOString();
    for (const k of Object.keys(MonitorApi.STAT_LABELS)) {
      const raw = overview[k];
      if (raw === undefined || raw === null) {
        continue;
      }
      const stat: Stat = {
        key: k,
        label: MonitorApi.STAT_LABELS[k],
        value: Number(raw),
        period: 'day',
        recordedAt: now,
      };
      stats.push(stat);
    }
    return { code: 0, message: res.message, data: stats } as ApiResponse<Stat[]>;
  }

  /** @deprecated 后端无 GET /v1/stats/{key}（统计只有 /v1/stats 整表与 /v1/stats/system 等子面） */
  async getStat(key: string): Promise<ApiResponse<Stat>> {
    throw new Error('后端无此端点：GET /v1/stats/{key}（统计面为 GET /v1/stats 整表）');
  }

  /** @deprecated 后端无时序指标端点（资源类真值走 GET /v1/monitor/resources） */
  async listMetrics(name?: string, params?: PageParams): Promise<ApiResponse<PageResult<MonitorMetric>>> {
    throw new Error('后端无此端点：GET /v1/monitor/metrics（资源真值走 GET /v1/monitor/resources）');
  }

  /** @deprecated 后端无时序指标写入端点 */
  async pushMetric(data: Partial<MonitorMetric>): Promise<ApiResponse<MonitorMetric>> {
    throw new Error('后端无此端点：POST /v1/monitor/metrics');
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

  /** 列出文件（GET /files 后端裸数组边界归一包成 PageResult；后端暂无目录层级，parentId 仅保留签名） */
  async listFiles(
    parentId?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<FileItem>>> {
    const res = asEnvelopeList<FileItem>(await this.client.get<FileItem[]>('/files'));
    const arr = (res.data ?? []) as FileItem[];
    return {
      code: 0, message: 'ok',
      data: { items: arr, total: arr.length, page: 1, size: arr.length },
    } as ApiResponse<PageResult<FileItem>>;
  }

  /** 获取单条文件项（FileInfo 裸对象边界归一） */
  async getFile(id: string): Promise<ApiResponse<FileItem>> {
    const res = await this.client.get<FileItem>(`/files/${id}`);
    return asEnvelope<FileItem>(res, ['file_id', 'filename']);
  }

  /** 更新文件项（FileInfo 裸对象边界归一） */
  async updateFile(id: string, data: Object): Promise<ApiResponse<FileItem>> {
    const res = await this.client.put<FileItem>(`/files/${id}`, data);
    return asEnvelope<FileItem>(res, ['file_id', 'filename']);
  }

  /** 删除文件项（后端返 {code,message} 信封） */
  async removeFile(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/files/${id}`);
  }

  // ========== NEURON 实体（真实端点；neuron 自述前缀挂 /api/neuron，无 /v1——P1-30）==========

  /**
   * neuron 挂载点 URL：后端 neuron.py 以模块自述 prefix="/neuron" 挂在 /api 下
   * （endpoints/__init__.py 表内前缀留空），真实路径是 /api/neuron/*；而移动端
   * baseUrl 是 {server}/api/v1，直接拼 '/neuron/...' 会得到 /api/v1/neuron/* → 404。
   * 这里从 baseUrl 剥去 /api/v1 还原源点，再拼真实挂载路径。
   */
  private neuronUrl(path: string): string {
    const base = this.client.getBaseUrl();
    const suffix = '/api/v1';
    const origin = base.endsWith(suffix) ? base.slice(0, base.length - suffix.length) : base;
    return `${origin}/api/neuron${path}`;
  }

  /** NEURON 实体列表（GET /api/neuron/entities?entity_type=&limit=，{success,data,total} 边界归一拆包回数组） */
  async listNeurons(entityType?: string, params?: PageParams): Promise<ApiResponse<NeuronEntityDto[]>> {
    const query: Record<string, Object> = {};
    if (entityType !== undefined && entityType.length > 0) query['entity_type'] = entityType;
    if (params && params.page !== undefined) query['page'] = params.page;
    if (params && params.size !== undefined) query['limit'] = params.size;
    const res = asEnvelopeSuccessData<Object>(await this.client.get<Object>(this.neuronUrl('/entities'), query));
    const payload = (res.data ?? []) as NeuronEntityDto[];
    return { code: res.code, message: res.message, data: payload } as ApiResponse<NeuronEntityDto[]>;
  }

  /** 创建 NEURON 实体（POST /api/neuron/entities {name,entity_type,metadata}，{success,data} 边界归一） */
  async createNeuronEntity(name: string, entityType: string, metadata: Record<string, Object>): Promise<ApiResponse<NeuronEntityDto>> {
    const body: Record<string, Object> = {
      'name': name,
      'entity_type': entityType,
      'metadata': metadata,
    };
    const res = await this.client.post<NeuronEntityDto>(this.neuronUrl('/entities'), body);
    return asEnvelopeSuccessData<NeuronEntityDto>(res);
  }

  /** NEURON 统计（GET /api/neuron/stats，{success,data} 边界归一拆包回 data） */
  async getNeuronStats(): Promise<ApiResponse<NeuronStatsDto>> {
    const res = asEnvelopeSuccessData<Object>(await this.client.get<Object>(this.neuronUrl('/stats')));
    const stats = (res.data ?? {}) as NeuronStatsDto;
    return { code: res.code, message: res.message, data: stats } as ApiResponse<NeuronStatsDto>;
  }

  /** NEURON 健康检查（GET /api/neuron/health，{success,status,components} 裸 dict 边界归一） */
  async getNeuronHealth(): Promise<ApiResponse<Object>> {
    const res = await this.client.get<Object>(this.neuronUrl('/health'));
    return asEnvelope<Object>(res, ['success', 'status', 'components']) as ApiResponse<Object>;
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

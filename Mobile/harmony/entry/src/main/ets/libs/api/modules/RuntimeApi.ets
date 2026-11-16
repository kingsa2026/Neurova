/**
 * RuntimeApi - 运行时层 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   scheduler.py @ /v1/scheduler：GET|POST /tasks、GET|PUT|DELETE /tasks/{id}、
 *     POST /tasks/{id}/run（裸数组/裸对象，无分页信封）
 *   trace.py @ /v1/trace：GET ""（裸数组 TraceListItem）、GET /{trace_id}（详情）
 *   sleep.py @ /v1/sleep：GET /{agent_id}/status、POST /{agent_id}/wake、
 *     PUT /{agent_id}/settings（SleepSettingsRequest.sleep_mode）
 *   firewall.py @ /v1/firewall：GET|POST /rules、PUT|DELETE /rules/{id}（裸数组）
 * 诚实边界：后端**无**上下文消息 CRUD、计算机任务登记、独立轨迹点、轨迹删除
 *   端点——对应方法直接抛错点名原因（不造假数据、不静默吞掉）。
 * 旧 /runtime/* 路径后端不存在，全部退役。
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

/** 休眠状态载荷（sleep.py SleepStatusResponse 投影） */
export interface SleepStatusDto {
  agent_id: string;
  is_sleeping: boolean;
  sleep_phase: string;
  last_sleep_time: number | null;
  last_wake_time: number | null;
  total_sleep_duration: number;
  sleep_cycles: number;
  next_wake: number | null;
}

/** 调度任务（scheduler.py ScheduledTaskResponse 投影） */
interface SchedulerTaskDto {
  task_id: string;
  name: string;
  description: string;
  scheduled_at: number | null;
  interval_seconds: number | null;
  cron_expression: string | null;
  agent_id: string;
  action: string;
  status: string;
  created_at: number;
  updated_at: number;
  last_run_at: number | null;
  next_run_at: number | null;
  run_count: number;
  max_runs: number | null;
}

/** 追踪列表条目（trace.py TraceListItem 投影） */
interface TraceListItemDto {
  id: string;
  name: string;
  status: string;
  duration_ms: number;
  steps_count: number;
  started_at: string | null;
}

/** 防火墙规则（firewall.py FirewallRule 投影） */
interface FirewallRuleDto {
  rule_id: string;
  name: string;
  rule_type: string;
  action: string;
  value: string;
  enabled: boolean;
  created_at: number;
  updated_at: number;
}

/** 秒级时间戳 → ISO 字符串（空值/0 回退 ''） */
function tsToIso(ts: number | null | undefined): string {
  if (ts === null || ts === undefined || ts <= 0) return '';
  return new Date(ts * 1000).toISOString();
}

/** 裸数组 → PageResult 本地分页（page 默认 1、size 默认 20） */
function pageOf<T>(arr: T[], params?: PageParams): PageResult<T> {
  const page = params && params.page !== undefined ? params.page : 1;
  const size = params && params.size !== undefined ? params.size : 20;
  const start = (Math.max(page, 1) - 1) * size;
  const items = arr.slice(start, start + size);
  const result: PageResult<T> = { items: items, total: arr.length, page: page, size: size };
  return result;
}

/** 后端 sleep_phase → 前端休眠模式（awake/rem 归一到 idle/light） */
function phaseToMode(phase: string): 'idle' | 'light' | 'deep' {
  if (phase === 'deep') return 'deep';
  if (phase === 'light' || phase === 'rem') return 'light';
  return 'idle';
}

/** 后端防火墙动作 → 前端动作词汇（block→deny） */
function fwActionFromBackend(action: string): 'allow' | 'deny' | 'ask' {
  if (action === 'allow') return 'allow';
  if (action === 'block') return 'deny';
  return 'ask';
}

/** 前端防火墙动作 → 后端动作词汇 */
function fwActionToBackend(action: string | undefined): string {
  if (action === 'allow') return 'allow';
  if (action === 'ask') return 'ask';
  return 'block';
}

export class RuntimeApi {
  private client: HttpClient;
  constructor(client: HttpClient) {
    this.client = client;
  }

  // ==================== ScheduleTask 调度任务（/v1/scheduler/tasks） ====================

  /** ScheduledTaskResponse → ScheduleTask（单源映射） */
  private static toScheduleTask(dto: SchedulerTaskDto): ScheduleTask {
    const payload: Record<string, Object> = {
      'action': dto.action,
      'description': dto.description,
      'run_count': dto.run_count,
    };
    const task: ScheduleTask = {
      id: dto.task_id,
      agentId: dto.agent_id,
      name: dto.name,
      cron: dto.cron_expression !== null ? dto.cron_expression : '',
      status: RuntimeApi.normTaskStatus(dto.status),
      lastRunAt: tsToIso(dto.last_run_at),
      nextRunAt: tsToIso(dto.next_run_at),
      payload: payload,
      createdAt: tsToIso(dto.created_at),
    };
    return task;
  }

  /** 后端任务状态 → 前端五值归一化 */
  private static normTaskStatus(status: string): 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' {
    if (status === 'running' || status === 'completed' || status === 'failed' || status === 'cancelled') {
      return status;
    }
    return 'pending';
  }

  /** 单条响应解包：data 缺失即抛错（不返回半空信封） */
  private static unwrapOne<T>(res: ApiResponse<T>, what: string): ApiResponse<T> {
    if (res.code !== 0 || !res.data) {
      throw new Error(res.message && res.message.length > 0 ? res.message : `${what}失败`);
    }
    return res;
  }

  /** 列出调度任务（agent_id 后端过滤；裸数组本地分页） */
  async listScheduleTasks(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ScheduleTask>>> {
    const query: Record<string, Object> = {
      'agent_id': agentId,
      'limit': 100,
    };
    const res = await this.client.get<SchedulerTaskDto[]>('/scheduler/tasks', query);
    const arr = res.data as Object as SchedulerTaskDto[];
    const tasks: ScheduleTask[] = [];
    for (const dto of arr) {
      tasks.push(RuntimeApi.toScheduleTask(dto));
    }
    const mapped: ApiResponse<PageResult<ScheduleTask>> = {
      code: res.code,
      message: res.message,
      data: pageOf(tasks, params),
    };
    return mapped;
  }

  /** 获取单条调度任务 */
  async getScheduleTask(taskId: string): Promise<ApiResponse<ScheduleTask>> {
    const res = await this.client.get<SchedulerTaskDto>(`/scheduler/tasks/${taskId}`);
    const ok = RuntimeApi.unwrapOne(res, '调度任务获取');
    const mapped: ApiResponse<ScheduleTask> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toScheduleTask(ok.data as Object as SchedulerTaskDto),
    };
    return mapped;
  }

  /** 创建调度任务（TaskCreate 契约：name/action 必填） */
  async createScheduleTask(data: Partial<ScheduleTask>): Promise<ApiResponse<ScheduleTask>> {
    const emptyPayload: Record<string, Object> = {};
    const parameters: Record<string, Object> = data.payload !== undefined ? data.payload : emptyPayload;
    const body: Record<string, Object> = {
      'name': data.name !== undefined ? data.name : '未命名任务',
      'action': 'custom',
      'agent_id': data.agentId !== undefined ? data.agentId : '',
      'parameters': parameters,
    };
    if (data.cron !== undefined && data.cron.length > 0) {
      body['cron_expression'] = data.cron;
    }
    const res = await this.client.post<SchedulerTaskDto>('/scheduler/tasks', body);
    const ok = RuntimeApi.unwrapOne(res, '调度任务创建');
    const mapped: ApiResponse<ScheduleTask> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toScheduleTask(ok.data as Object as SchedulerTaskDto),
    };
    return mapped;
  }

  /** 更新调度任务；status='running' 语义为手动触发，改走 POST /tasks/{id}/run */
  async updateScheduleTask(
    taskId: string,
    data: Partial<ScheduleTask>,
  ): Promise<ApiResponse<ScheduleTask>> {
    if (data.status === 'running') {
      return this.runScheduleTask(taskId);
    }
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['name'] = data.name;
    if (data.cron !== undefined) body['cron_expression'] = data.cron;
    if (data.agentId !== undefined) body['agent_id'] = data.agentId;
    const res = await this.client.put<SchedulerTaskDto>(`/scheduler/tasks/${taskId}`, body);
    const ok = RuntimeApi.unwrapOne(res, '调度任务更新');
    const mapped: ApiResponse<ScheduleTask> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toScheduleTask(ok.data as Object as SchedulerTaskDto),
    };
    return mapped;
  }

  /** 手动触发任务（scheduler.py POST /tasks/{id}/run） */
  async runScheduleTask(taskId: string): Promise<ApiResponse<ScheduleTask>> {
    const body: Record<string, Object> = {};
    const res = await this.client.post<SchedulerTaskDto>(`/scheduler/tasks/${taskId}/run`, body);
    const ok = RuntimeApi.unwrapOne(res, '调度任务触发');
    const mapped: ApiResponse<ScheduleTask> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toScheduleTask(ok.data as Object as SchedulerTaskDto),
    };
    return mapped;
  }

  /** 删除调度任务 */
  async removeScheduleTask(taskId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/scheduler/tasks/${taskId}`);
  }

  // ==================== ContextMessage 上下文消息（后端无 CRUD 端点） ====================
  //
  // 后端 /v1/context 只提供构建/统计/注入，无消息列表 CRUD。相关操作直接抛错点名。

  /** 列出上下文消息（后端无对应端点，显式失败） */
  async listContextMessages(
    sessionId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ContextMessage>>> {
    throw new Error('后端暂未提供上下文消息列表端点');
  }

  /** 获取单条上下文消息（后端无对应端点，显式失败） */
  async getContextMessage(messageId: string): Promise<ApiResponse<ContextMessage>> {
    throw new Error('后端暂未提供上下文消息端点');
  }

  /** 删除上下文消息（后端无对应端点，显式失败） */
  async removeContextMessage(messageId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端暂未提供上下文消息删除端点');
  }

  // ==================== ComputerTask 计算机任务（后端无登记端点） ====================
  //
  // 后端 /v1/computer 只提供即时操作（screenshot/click/type/shell 等）与 /status、/doctor，
  // 无任务列表 CRUD。相关操作直接抛错点名。

  /** 列出计算机任务（后端无对应端点，显式失败） */
  async listComputerTasks(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<ComputerTask>>> {
    throw new Error('后端暂未提供计算机任务列表端点');
  }

  /** 获取单条计算机任务（后端无对应端点，显式失败） */
  async getComputerTask(taskId: string): Promise<ApiResponse<ComputerTask>> {
    throw new Error('后端暂未提供计算机任务端点');
  }

  /** 创建计算机任务（后端无对应端点，显式失败） */
  async createComputerTask(data: Partial<ComputerTask>): Promise<ApiResponse<ComputerTask>> {
    throw new Error('后端暂未提供计算机任务登记端点');
  }

  /** 删除计算机任务（后端无对应端点，显式失败） */
  async removeComputerTask(taskId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端暂未提供计算机任务删除端点');
  }

  // ==================== TraceEntry 追踪（/v1/trace） ====================

  /** TraceListItem → TraceEntry（单源映射；level 后端无词汇，统一 info） */
  private static toTraceEntry(dto: TraceListItemDto, agentId: string): TraceEntry {
    const payload: Record<string, Object> = {
      'status': dto.status,
      'steps_count': dto.steps_count,
    };
    const entry: TraceEntry = {
      id: dto.id,
      agentId: agentId,
      sessionId: '',
      level: 'info',
      event: dto.name,
      payload: payload,
      timestamp: dto.started_at !== null ? dto.started_at : '',
      durationMs: dto.duration_ms,
    };
    return entry;
  }

  /** 列出追踪条目（agent_id 后端过滤；裸数组本地分页） */
  async listTraces(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<TraceEntry>>> {
    const query: Record<string, Object> = {
      'agent_id': agentId,
      'limit': 100,
    };
    const res = await this.client.get<TraceListItemDto[]>('/trace', query);
    const arr = res.data as Object as TraceListItemDto[];
    const entries: TraceEntry[] = [];
    for (const dto of arr) {
      entries.push(RuntimeApi.toTraceEntry(dto, agentId));
    }
    const mapped: ApiResponse<PageResult<TraceEntry>> = {
      code: res.code,
      message: res.message,
      data: pageOf(entries, params),
    };
    return mapped;
  }

  /** 获取单条追踪详情（trace.py GET /{trace_id}，含 events/tool_calls） */
  async getTrace(traceId: string): Promise<ApiResponse<TraceEntry>> {
    const res = await this.client.get<Object>(`/trace/${traceId}`);
    const rec = res.data as Object as Record<string, Object>;
    if (res.code !== 0 || !rec || rec['id'] === undefined) {
      throw new Error(res.message && res.message.length > 0 ? res.message : '轨迹获取失败');
    }
    const item: TraceListItemDto = {
      id: `${rec['id']}`,
      name: rec['name'] !== undefined ? `${rec['name']}` : '',
      status: rec['status'] !== undefined ? `${rec['status']}` : 'completed',
      duration_ms: rec['duration_ms'] !== undefined ? Number(rec['duration_ms']) : 0,
      steps_count: rec['steps_count'] !== undefined ? Number(rec['steps_count']) : 0,
      started_at: rec['started_at'] !== undefined ? `${rec['started_at']}` : null,
    };
    const mapped: ApiResponse<TraceEntry> = {
      code: 0,
      message: res.message,
      data: RuntimeApi.toTraceEntry(item, ''),
    };
    return mapped;
  }

  /** 删除追踪条目（后端无 DELETE 端点，显式失败） */
  async removeTrace(traceId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端暂未提供轨迹删除端点');
  }

  // ==================== TrajectoryPoint 轨迹点（后端无独立端点） ====================
  //
  // 后端轨迹数据在 /v1/trace/{id}/events 内，无独立轨迹点列表。直接抛错点名。

  /** 列出轨迹点（后端无对应端点，显式失败） */
  async listTrajectory(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<TrajectoryPoint>>> {
    throw new Error('后端暂未提供轨迹点列表端点');
  }

  /** 获取单条轨迹点（后端无对应端点，显式失败） */
  async getTrajectoryPoint(pointId: string): Promise<ApiResponse<TrajectoryPoint>> {
    throw new Error('后端暂未提供轨迹点端点');
  }

  // ==================== SleepStatus 休眠（/v1/sleep） ====================

  /** SleepStatusResponse → SleepStatus（单源映射） */
  private static toSleepStatus(dto: SleepStatusDto): SleepStatus {
    const status: SleepStatus = {
      agentId: dto.agent_id,
      isSleeping: dto.is_sleeping,
      sleepSince: tsToIso(dto.last_sleep_time),
      wakeAt: tsToIso(dto.next_wake),
      mode: phaseToMode(dto.sleep_phase),
      pendingTasks: 0,
    };
    return status;
  }

  /** 获取休眠状态（sleep.py GET /{agent_id}/status） */
  async getSleepStatus(agentId: string): Promise<ApiResponse<SleepStatus>> {
    const res = await this.client.get<SleepStatusDto>(`/sleep/${agentId}/status`);
    const ok = RuntimeApi.unwrapOne(res, '休眠状态获取');
    const mapped: ApiResponse<SleepStatus> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toSleepStatus(ok.data as Object as SleepStatusDto),
    };
    return mapped;
  }

  /** 设置休眠模式（sleep.py PUT /{agent_id}/settings 的 sleep_mode 字段） */
  async setSleepMode(agentId: string, mode: 'idle' | 'light' | 'deep'): Promise<ApiResponse<SleepStatus>> {
    const body: Record<string, Object> = { 'sleep_mode': mode };
    const res = await this.client.put<SleepStatusDto>(`/sleep/${agentId}/settings`, body);
    const ok = RuntimeApi.unwrapOne(res, '休眠模式设置');
    const mapped: ApiResponse<SleepStatus> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toSleepStatus(ok.data as Object as SleepStatusDto),
    };
    return mapped;
  }

  /** 获取休眠状态原始投影（新消费方优先用此） */
  async getSleepStatusDto(agentId: string): Promise<ApiResponse<SleepStatusDto>> {
    return this.client.get<SleepStatusDto>(`/sleep/${agentId}/status`);
  }

  /** 唤醒 Agent（sleep.py POST /{agent_id}/wake） */
  async awaken(agentId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/sleep/${agentId}/wake`, body);
  }

  // ==================== FirewallRule 防火墙（/v1/firewall/rules） ====================

  /** FirewallRule → 前端 FirewallRule（单源映射；后端为全局规则，无 agent 维度） */
  private static toFirewallRule(dto: FirewallRuleDto): FirewallRule {
    const rule: FirewallRule = {
      id: dto.rule_id,
      agentId: '',
      resource: dto.value,
      action: fwActionFromBackend(dto.action),
      scope: 'both',
      enabled: dto.enabled,
      createdAt: tsToIso(dto.created_at),
    };
    return rule;
  }

  /** 列出防火墙规则（裸数组本地分页） */
  async listFirewallRules(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<FirewallRule>>> {
    const query: Record<string, Object> = { 'limit': 100 };
    const res = await this.client.get<FirewallRuleDto[]>('/firewall/rules', query);
    const arr = res.data as Object as FirewallRuleDto[];
    const rules: FirewallRule[] = [];
    for (const dto of arr) {
      rules.push(RuntimeApi.toFirewallRule(dto));
    }
    const mapped: ApiResponse<PageResult<FirewallRule>> = {
      code: res.code,
      message: res.message,
      data: pageOf(rules, params),
    };
    return mapped;
  }

  /** 获取单条防火墙规则（后端无单条 GET，从列表定位；不存在即抛错） */
  async getFirewallRule(ruleId: string): Promise<ApiResponse<FirewallRule>> {
    const query: Record<string, Object> = { 'limit': 100 };
    const res = await this.client.get<FirewallRuleDto[]>('/firewall/rules', query);
    const arr = res.data as Object as FirewallRuleDto[];
    for (const dto of arr) {
      if (dto.rule_id === ruleId) {
        const mapped: ApiResponse<FirewallRule> = {
          code: 0,
          message: res.message,
          data: RuntimeApi.toFirewallRule(dto),
        };
        return mapped;
      }
    }
    throw new Error('防火墙规则不存在');
  }

  /** 创建防火墙规则（FirewallRuleCreate 契约：name/value 必填） */
  async createFirewallRule(data: Partial<FirewallRule>): Promise<ApiResponse<FirewallRule>> {
    const resource = data.resource !== undefined ? data.resource : '';
    const body: Record<string, Object> = {
      'name': resource.length > 0 ? resource : '未命名规则',
      'rule_type': 'ip',
      'action': fwActionToBackend(data.action),
      'value': resource,
      'enabled': data.enabled !== undefined ? data.enabled : true,
    };
    const res = await this.client.post<FirewallRuleDto>('/firewall/rules', body);
    const ok = RuntimeApi.unwrapOne(res, '防火墙规则创建');
    const mapped: ApiResponse<FirewallRule> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toFirewallRule(ok.data as Object as FirewallRuleDto),
    };
    return mapped;
  }

  /** 更新防火墙规则（后端 PUT 为全量 FirewallRuleCreate——先取原规则合并再提交） */
  async updateFirewallRule(
    ruleId: string,
    data: Partial<FirewallRule>,
  ): Promise<ApiResponse<FirewallRule>> {
    const current = await this.getFirewallRule(ruleId);
    const base = current.data;
    const resource = data.resource !== undefined ? data.resource : (base !== null ? base.resource : '');
    const body: Record<string, Object> = {
      'name': resource.length > 0 ? resource : '未命名规则',
      'rule_type': 'ip',
      'action': fwActionToBackend(data.action !== undefined ? data.action : (base !== null ? base.action : undefined)),
      'value': resource,
      'enabled': data.enabled !== undefined ? data.enabled : (base !== null ? base.enabled : true),
    };
    const res = await this.client.put<FirewallRuleDto>(`/firewall/rules/${ruleId}`, body);
    const ok = RuntimeApi.unwrapOne(res, '防火墙规则更新');
    const mapped: ApiResponse<FirewallRule> = {
      code: ok.code,
      message: ok.message,
      data: RuntimeApi.toFirewallRule(ok.data as Object as FirewallRuleDto),
    };
    return mapped;
  }

  /** 删除防火墙规则 */
  async removeFirewallRule(ruleId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/firewall/rules/${ruleId}`);
  }
}

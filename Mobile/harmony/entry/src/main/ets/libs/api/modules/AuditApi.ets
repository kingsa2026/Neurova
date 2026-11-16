/**
 * AuditApi - 审计日志 API 模块（R6 新增，端点经后端源码核对 2026-11-17）
 *
 * 后端事实源（audit.py @ /v1/audit，全部 require_admin）：
 *   GET  /audit          → 信封 {code,data:{items[AuditRecord],total,page,page_size,stats}}
 *                          AuditRecord：{id,timestamp(ISO Z),user,action,resource,details}
 *                          stats：{total,today,warnings}
 *   GET  /audit/export   → 裸数组（JSONResponse 附件下载，同列表筛选参数）
 *   POST /audit/search   → 裸数组 List[AuditLog]{log_id,timestamp(float),user_id,action,
 *                          resource_type,resource_id,details,ip_address?,user_agent?}
 *   GET  /audit/stats    → 裸 AuditStats{total_logs,unique_users,unique_actions,
 *                          action_counts,resource_type_counts}
 *
 * 后端 action 是自由文本（如 "Login successful"），不是前端旧 mock 的封闭枚举——
 * 筛选/着色一律按开放集合处理，未知值兜默认，不抛错。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import { ApiResponse } from '../../types';

/** 列表条目（audit.py _entry_to_record 契约） */
export interface AuditRecordDto {
  id: string;
  timestamp: string;          // ISO8601 Z
  user: string;
  action: string;
  resource: string;
  details: Record<string, Object> | null;
}

/** 列表信封 data（audit.py get_audit_logs） */
export interface AuditPageDto {
  items: AuditRecordDto[];
  total: number;
  page: number;
  page_size: number;
  stats: AuditPageStatsDto;
}

/** 列表页统计（与 /stats 端点的 AuditStats 是两套口径） */
export interface AuditPageStatsDto {
  total: number;
  today: number;
  warnings: number;
}

/** /search 命中条目（audit.py AuditLog 模型，蛇形字段原样透传） */
export interface AuditSearchHitDto {
  log_id: string;
  timestamp: number;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, Object>;
  ip_address: string | null;
  user_agent: string | null;
}

/** /stats 端点口径（audit.py AuditStats 模型） */
export interface AuditStatsDto {
  total_logs: number;
  unique_users: number;
  unique_actions: number;
  action_counts: Record<string, number>;
  resource_type_counts: Record<string, number>;
}

/** 列表筛选参数（全部可选） */
export interface AuditListParams {
  page?: number;
  pageSize?: number;
  user?: string;
  action?: string;
  start?: string;             // epoch 或 ISO8601（后端 _parse_time 两吃）
  end?: string;
}

/** 搜索请求体（audit.py AuditSearchRequest） */
export interface AuditSearchBody {
  query?: string;
  userId?: string;
  action?: string;
  resourceType?: string;
  startTime?: number;
  endTime?: number;
  limit?: number;
}

export class AuditApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 审计日志分页列表（GET /audit，信封原样透传——data 已含分页与统计） */
  async list(params?: AuditListParams): Promise<ApiResponse<AuditPageDto>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.page !== undefined) {
        query['page'] = params.page;
      }
      if (params.pageSize !== undefined) {
        query['page_size'] = params.pageSize;
      }
      if (params.user !== undefined && params.user.length > 0) {
        query['user'] = params.user;
      }
      if (params.action !== undefined && params.action.length > 0) {
        query['action'] = params.action;
      }
      if (params.start !== undefined && params.start.length > 0) {
        query['start'] = params.start;
      }
      if (params.end !== undefined && params.end.length > 0) {
        query['end'] = params.end;
      }
    }
    return this.client.get<AuditPageDto>('/audit', query);
  }

  /** 导出（GET /audit/export，裸数组边界归一；移动端无文件落盘，取回条数由页面提示） */
  async exportAudit(params?: AuditListParams): Promise<ApiResponse<Object[]>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.user !== undefined && params.user.length > 0) {
        query['user'] = params.user;
      }
      if (params.action !== undefined && params.action.length > 0) {
        query['action'] = params.action;
      }
      if (params.start !== undefined && params.start.length > 0) {
        query['start'] = params.start;
      }
      if (params.end !== undefined && params.end.length > 0) {
        query['end'] = params.end;
      }
    }
    const res = await this.client.get<Object[]>('/audit/export', query);
    return asEnvelopeList<Object>(res as ApiResponse<Object[]>);
  }

  /** 搜索（POST /audit/search，裸数组边界归一） */
  async search(body: AuditSearchBody): Promise<ApiResponse<AuditSearchHitDto[]>> {
    const payload: Record<string, Object> = {};
    if (body.query !== undefined) {
      payload['query'] = body.query;
    }
    if (body.userId !== undefined) {
      payload['user_id'] = body.userId;
    }
    if (body.action !== undefined) {
      payload['action'] = body.action;
    }
    if (body.resourceType !== undefined) {
      payload['resource_type'] = body.resourceType;
    }
    if (body.startTime !== undefined) {
      payload['start_time'] = body.startTime;
    }
    if (body.endTime !== undefined) {
      payload['end_time'] = body.endTime;
    }
    if (body.limit !== undefined) {
      payload['limit'] = body.limit;
    }
    const res = await this.client.post<AuditSearchHitDto[]>('/audit/search', payload);
    return asEnvelopeList<AuditSearchHitDto>(res as ApiResponse<AuditSearchHitDto[]>);
  }

  /** 全局统计（GET /audit/stats，裸对象边界归一） */
  async stats(): Promise<ApiResponse<AuditStatsDto>> {
    const res = await this.client.get<AuditStatsDto>('/audit/stats');
    return asEnvelope<AuditStatsDto>(res, ['total_logs', 'unique_users']) as ApiResponse<AuditStatsDto>;
  }
}

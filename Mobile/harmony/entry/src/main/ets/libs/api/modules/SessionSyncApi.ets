/**
 * SessionSyncApi - 会话同步域 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源：session_sync.py @ /v1/sync（旧 /session-syncs 端点后端不存在，全部退役）：
 *   POST   /sessions {agent_id,external_id?,metadata?} → SessionResponse（user_id 以 token 主体为准）
 *   GET    /sessions?agent_id=&status= → {total,sessions:[SessionResponse]}
 *   GET    /sessions/{id} → SessionResponse
 *   DELETE /sessions/{id} → {success,session_id}（结束会话）
 *   GET    /sessions/{id}/history?limit= → {session_id,total,events}
 *   POST   /sessions/{id}/messages {content,channel_type,metadata} → {success,event_id,sent_to_channels}
 *   GET    /statistics、GET /connections
 * 实时同步走 WS /sync/ws/{session_id}（本模块只封装 REST 面）；
 * 无 PUT 更新、无手动 trigger 端点——对应方法 throw 点名。
 */

import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import {
  ApiResponse,
  PageParams,
  PageResult,
} from '../../types';

/** 同步会话（session_sync.SessionResponse 逐字段投影） */
export interface SyncSessionDto {
  session_id: string;
  user_id: string;
  agent_id: string;
  conversation_id: string;
  created_at: string;
  last_activity: string;
  status: string;
  active_channels: string[];
  history_size: number;
}

/** 创建同步会话 body（session_sync.CreateSessionRequest 契约；user_id 由 token 主体决定，不外传） */
export interface SyncSessionCreateBody {
  agent_id: string;
  external_id?: string;
  metadata?: Record<string, Object>;
}

/** 发送消息 body（session_sync.SendMessageRequest 契约） */
export interface SyncSendMessageBody {
  content: string;
  channel_type: string;
  metadata?: Record<string, Object>;
}

/** 会话历史（get_session_history 投影） */
export interface SyncHistoryDto {
  session_id: string;
  total: number;
  events: Object[];
}

export class SessionSyncApi {
  private client: HttpClient;
  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 列出同步会话（GET /sync/sessions，后端裸 {total,sessions} 边界归一后拆包成 PageResult；分页参数仅保留签名，后端整表返回） */
  async list(agentId?: string, params?: PageParams): Promise<ApiResponse<PageResult<SyncSessionDto>>> {
    const query: Record<string, Object> = {};
    if (agentId !== undefined && agentId.length > 0) query['agent_id'] = agentId;
    const res = asEnvelope<Object>(await this.client.get<Object>('/sync/sessions', query), ['total', 'sessions']);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const sessions = (payload['sessions'] ?? []) as SyncSessionDto[];
    const total = Number(payload['total'] ?? sessions.length);
    return {
      code: res.code, message: res.message,
      data: { items: sessions, total: total, page: 1, size: sessions.length },
    } as ApiResponse<PageResult<SyncSessionDto>>;
  }

  /** 获取单条同步会话（SessionResponse 裸对象边界归一） */
  async get(sessionId: string): Promise<ApiResponse<SyncSessionDto>> {
    const res = await this.client.get<SyncSessionDto>(`/sync/sessions/${sessionId}`);
    return asEnvelope<SyncSessionDto>(res, ['session_id', 'status']);
  }

  /** 创建同步会话（POST /sync/sessions，SessionResponse 裸对象边界归一） */
  async create(body: SyncSessionCreateBody): Promise<ApiResponse<SyncSessionDto>> {
    const res = await this.client.post<SyncSessionDto>('/sync/sessions', body);
    return asEnvelope<SyncSessionDto>(res, ['session_id', 'status']);
  }

  /** 结束（删除）同步会话（DELETE /sync/sessions/{id}，{success,...} 裸 dict 边界归一） */
  async remove(sessionId: string): Promise<ApiResponse<Object>> {
    const res = await this.client.delete<Object>(`/sync/sessions/${sessionId}`);
    return asEnvelope<Object>(res, ['success']) as ApiResponse<Object>;
  }

  /** 会话历史（GET /sync/sessions/{id}/history，裸 {session_id,total,events} 边界归一） */
  async getHistory(sessionId: string, limit?: number): Promise<ApiResponse<SyncHistoryDto>> {
    const query: Record<string, Object> = {};
    if (limit !== undefined) query['limit'] = limit;
    const res = await this.client.get<SyncHistoryDto>(`/sync/sessions/${sessionId}/history`, query);
    return asEnvelope<SyncHistoryDto>(res, ['session_id', 'events']);
  }

  /** 发送消息（REST 降级通道，POST /sync/sessions/{id}/messages，{success,...} 裸 dict 边界归一） */
  async sendMessage(sessionId: string, body: SyncSendMessageBody): Promise<ApiResponse<Object>> {
    const res = await this.client.post<Object>(`/sync/sessions/${sessionId}/messages`, body);
    return asEnvelope<Object>(res, ['success']) as ApiResponse<Object>;
  }

  /** 同步统计（GET /sync/statistics；后端返回统计 dict，形状由 manager 决定，原样透传） */
  async statistics(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/sync/statistics');
  }

  /** 活跃连接信息（GET /sync/connections，按调用者会话过滤；裸 {total,connections} 边界归一） */
  async connections(): Promise<ApiResponse<Object>> {
    const res = await this.client.get<Object>('/sync/connections');
    return asEnvelope<Object>(res, ['total', 'connections']) as ApiResponse<Object>;
  }

  /** @deprecated 后端无 PUT /sync/sessions/{id}（会话状态由服务端流转） */
  async update(sessionId: string, data: Object): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：PUT /v1/sync/sessions/{id}（会话状态由服务端流转，无更新口）');
  }

  /** @deprecated 后端无手动触发同步端点（实时同步走 WS /v1/sync/ws/{session_id}） */
  async trigger(sessionId: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：POST /v1/session-syncs/{id}/trigger（实时同步走 WS /v1/sync/ws/{session_id}）');
  }
}

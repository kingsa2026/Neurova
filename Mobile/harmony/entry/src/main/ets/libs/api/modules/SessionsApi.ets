/**
 * SessionsApi - 会话 API 模块（与 PC 端 ChatSessionSidebar 同源）
 *
 * 后端事实源：neurova/api/endpoints/console.py（挂 /v1/console 前缀）。
 * 端点形状以 console.py 实测为准（2026-11-16 读源核对）：
 *   GET    /console/chat/sessions                 → {code:0,data:{sessions:[摘要],total}}
 *   PUT    /console/chat/sessions/{id}            → 重命名
 *   POST   /console/chat/sessions/{id}/pin        → 置顶/取消
 *   POST   /console/chat/sessions/{id}/archive    → 归档
 *   POST   /console/chat/sessions/{id}/unarchive  → 恢复
 *   POST   /console/chat/sessions/{id}/fork       → 分叉
 *   GET    /console/chat/sessions/archived        → 归档会话列表
 *   DELETE /console/chat/sessions/{id}            → 删除
 *   GET    /console/chat/history?session_id=      → {code:0,data:{messages:[{role,content}],session_id}}
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 会话摘要（console.py get_chat_sessions 摘要形状原样） */
export interface ChatSession {
  id: string;
  title: string;
  agent_id: string;
  created_at: string;
  updated_at: string;
  pinned: boolean;
  sort_order: number;
  source_channel: string;
  channel_name: string;
}

/** GET sessions 的 data 载荷 */
export interface ChatSessionList {
  sessions: ChatSession[];
  total: number;
}

/** 历史消息（session_manager 存储形状：{role, content}） */
export interface ChatHistoryMessage {
  role: string;
  content: string;
}

/** GET /console/chat/history 的 data 载荷 */
export interface ChatHistoryPayload {
  messages: ChatHistoryMessage[];
  session_id: string;
}

/** GET /console/chat/sessions/{id}/timeline 的 data 载荷（事件为 JSONL 行投影） */
export interface ChatTimelinePayload {
  session_id: string;
  events: Array<Record<string, Object>>;
  total: number;
}

/** 重命名请求体（ArkTS 禁非空对象字面量直接标注 Record，走接口声明） */
export interface RenameRequest {
  title: string;
}

/** 置顶请求体（console.py PinSessionRequest 契约：pinned 必填） */
export interface PinRequest {
  pinned: boolean;
}

export class SessionsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 会话列表（agent_id 可选过滤；空串取全部） */
  async listAll(agentId: string): Promise<ApiResponse<ChatSessionList>> {
    const path = agentId.length > 0
      ? `/console/chat/sessions?agent_id=${agentId}`
      : '/console/chat/sessions';
    return this.client.get<ChatSessionList>(path);
  }

  /** 归档会话列表（console.py get_archived_chat_sessions；agent_id 可选过滤） */
  async listArchived(agentId: string): Promise<ApiResponse<ChatSessionList>> {
    const path = agentId.length > 0
      ? `/console/chat/sessions/archived?agent_id=${agentId}`
      : '/console/chat/sessions/archived';
    return this.client.get<ChatSessionList>(path);
  }

  /** 重命名 */
  async rename(sessionId: string, title: string): Promise<ApiResponse<Object>> {
    const body: RenameRequest = { title: title };
    return this.client.put<Object>(`/console/chat/sessions/${sessionId}`, body);
  }

  /**
   * 置顶/取消置顶（后端 PinSessionRequest 必填 {pinned: bool}——P1-32）。
   * 传 pinned 显式指定；不传时按"翻转当前态"语义：先查列表取该会话当前 pinned，取反提交。
   */
  async pin(sessionId: string, pinned?: boolean): Promise<ApiResponse<Object>> {
    let target = pinned;
    if (target === undefined) {
      const list = await this.listAll('');
      if (list.code !== 0 || !list.data) {
        throw new Error(list.message && list.message.length > 0 ? list.message : '会话状态获取失败');
      }
      let current = false;
      for (const s of list.data.sessions) {
        if (s.id === sessionId) {
          current = s.pinned;
          break;
        }
      }
      target = !current;
    }
    const body: PinRequest = { pinned: target };
    return this.client.post<Object>(`/console/chat/sessions/${sessionId}/pin`, body);
  }

  /** 归档 */
  async archive(sessionId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/console/chat/sessions/${sessionId}/archive`, body);
  }

  /** 从归档恢复 */
  async unarchive(sessionId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/console/chat/sessions/${sessionId}/unarchive`, body);
  }

  /** 分叉出新会话 */
  async fork(sessionId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/console/chat/sessions/${sessionId}/fork`, body);
  }

  /** 删除 */
  async remove(sessionId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/console/chat/sessions/${sessionId}`);
  }

  /** 历史（返回 {role,content} 列表，旧→新） */
  async history(sessionId: string): Promise<ApiResponse<ChatHistoryPayload>> {
    return this.client.get<ChatHistoryPayload>(`/console/chat/history?session_id=${sessionId}`);
  }

  /** 会话时间线（append-only 事件重放；offset=已缓存条数做增量同步，total 恒为全量条数） */
  async timeline(sessionId: string, offset: number): Promise<ApiResponse<ChatTimelinePayload>> {
    return this.client.get<ChatTimelinePayload>(
      `/console/chat/sessions/${sessionId}/timeline?offset=${offset}`);
  }
}

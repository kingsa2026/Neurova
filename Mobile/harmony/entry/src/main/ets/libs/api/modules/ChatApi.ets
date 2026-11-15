/**
 * ChatApi - 对话历史 API 模块
 *
 * 注意：实时聊天通过 WebSocket 进行（chat:send/chat:chunk/chat:done），
 * 此模块仅用于查询历史消息。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, Message, PageResult, PageParams } from '../../types';

export class ChatApi {
  constructor(private client: HttpClient) {}

  /** 获取会话消息历史 */
  async messages(sessionId: string, params?: PageParams): Promise<ApiResponse<PageResult<Message>>> {
    return this.client.get<PageResult<Message>>(
      `/v1/sessions/${sessionId}/messages`,
      params as Record<string, Object>,
    );
  }

  /** 删除单条消息 */
  async removeMessage(sessionId: string, messageId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/sessions/${sessionId}/messages/${messageId}`);
  }
}

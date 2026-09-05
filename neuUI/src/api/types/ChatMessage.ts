/**
 * 聊天消息相关类型定义
 * 支持多模态（文本、图片、视频、文件等）
 */

/**
 * 附件类型
 */
export type AttachmentType = 'image' | 'video' | 'audio' | 'file';

/**
 * 附件信息
 */
export interface Attachment {
  id: string;
  name: string;
  type: AttachmentType;
  url?: string;
  size?: number;
  mimeType?: string;
  metadata?: Record<string, unknown>;
}

/**
 * 消息元数据
 */
export interface MessageMetadata {
  model?: string;
  tokens?: number;
  latency?: number;
  attachment_ids?: string[];
  [key: string]: unknown;
}

/**
 * 聊天消息
 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string | Date;
  attachments?: Attachment[];
  metadata?: MessageMetadata;
  conversation_id?: string;
}

/**
 * 会话信息
 */
export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  metadata?: Record<string, unknown>;
}

/**
 * 发送消息请求
 */
export interface SendMessageRequest {
  message: string;
  session_id?: string;
  agent_id?: string;
  stream?: boolean;
  save_memory?: boolean;
  attachments?: AttachmentRequest[];
}

/**
 * 附件请求
 */
export interface AttachmentRequest {
  filename: string;
  content_type?: string;
  size?: number;
}

/**
 * 发送消息响应
 */
export interface SendMessageResponse {
  reply: string;
  type: string;
  agent_id: string;
  session_id?: string;
  attachment_ids?: string[];
  metadata?: Record<string, unknown>;
  timestamp: string;
}

/**
 * 获取会话列表响应
 */
export interface GetConversationsResponse {
  conversations: Conversation[];
  total: number;
}

/**
 * 获取消息历史响应
 */
export interface GetMessagesResponse {
  messages: ChatMessage[];
  total: number;
  has_more: boolean;
}

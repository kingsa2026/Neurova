import { request } from '@/api';

export interface GroupChat {
  group_id: string;
  project_id: string;
  name: string;
  description?: string;
  created_by: string;
  members: string[];
  created_at: string;
  updated_at: string;
}

export interface GroupCreate {
  group_id: string;
  name: string;
  description?: string;
  members: string[];
  max_members?: number;
  message_rate_limit?: number;
  enable_summary?: boolean;
}

export interface GroupStats {
  member_count: number;
  message_count: number;
  unread_count: number;
  last_message?: string;
  last_message_time?: string;
}

export interface ChatMessage {
  message_id: string;
  group_id: string;
  sender_id: string;
  content: string;
  message_type: string;
  priority: string;
  created_at: string;
  reply_to?: string;
  is_edited?: boolean;
  edited_at?: string;
  is_recalled?: boolean;
  recalled_at?: string;
  recalled_by?: string;
}

export interface MessageSend {
  group_id: string;
  content: string;
  message_type?: string;
  reply_to?: string;
}

export interface MessageEdit {
  content: string;
}

export interface MessageSummary {
  group_id: string;
  summary: string;
  message_count: number;
  participant_count: number;
}

export interface ReadStatus {
  message_id: string;
  read_by: Array<{ user_id: string; read_at: string }>;
  read_count: number;
}

export interface Member {
  id: string;
  name: string;
  type: 'agent' | 'user';
}

export interface TaskSuggestion {
  id: string;
  title: string;
  description?: string;
  priority?: string;
  assignee?: string;
  due_date?: string;
  completed: boolean;
}

export interface DecisionOption {
  id: string;
  title: string;
  pros: string[];
  cons: string[];
  recommendation?: number;
}

export interface MeetingNoteItem {
  type: 'discussion' | 'decision' | 'action';
  content: string;
  owner?: string;
  deadline?: string;
}

export interface AIRequest {
  message_context: string;
  max_length?: number;
  temperature?: number;
}

export interface AIResult {
  type: string;
  content: string;
  timestamp: string;
  tasks?: TaskSuggestion[];
  decisions?: DecisionOption[];
  notes?: MeetingNoteItem[];
}

export const groupChatAPI = {
  list: (projectId: string) =>
    request.get<{ success: boolean; data: GroupChat[] }>(`/projects/${projectId}/groups`),

  get: (projectId: string, groupId: string) =>
    request.get<{ success: boolean; data: GroupChat & Partial<GroupStats> }>(`/projects/${projectId}/groups/${groupId}`),

  create: (projectId: string, data: GroupCreate) =>
    request.post<{ success: boolean; data: GroupChat }>(`/projects/${projectId}/groups`, data),

  update: (projectId: string, groupId: string, data: { name?: string; description?: string }) =>
    request.put<{ success: boolean; data: GroupChat }>(`/projects/${projectId}/groups/${groupId}`, {}, { params: data }),

  delete: (projectId: string, groupId: string) =>
    request.delete<{ success: boolean }>(`/projects/${projectId}/groups/${groupId}`),

  getStats: (projectId: string, groupId: string) =>
    request.get<{ success: boolean; data: GroupStats }>(`/projects/${projectId}/groups/${groupId}/stats`),

  getMessages: (projectId: string, groupId: string, params?: {
    since?: string;
    limit?: number;
    sender_id?: string;
  }) =>
    request.get<{ success: boolean; data: ChatMessage[] }>(
      `/projects/${projectId}/groups/${groupId}/messages`,
      { params }
    ),

  sendMessage: (projectId: string, data: MessageSend, senderId: string) =>
    request.post<{ success: boolean; data: { message_id: string; priority: string; created_at: string } }>(
      `/projects/${projectId}/groups/messages`,
      data,
      { params: { sender_id: senderId } }
    ),

  editMessage: (projectId: string, groupId: string, messageId: string, data: MessageEdit, senderId: string) =>
    request.put<{ success: boolean; data: Record<string, unknown> }>(
      `/projects/${projectId}/groups/${groupId}/messages/${messageId}`,
      data,
      { params: { sender_id: senderId } }
    ),

  recallMessage: (projectId: string, groupId: string, messageId: string, senderId: string) =>
    request.delete<{ success: boolean }>(
      `/projects/${projectId}/groups/${groupId}/messages/${messageId}/recall`,
      { params: { sender_id: senderId } }
    ),

  getSummary: (projectId: string, groupId: string, since?: string) =>
    request.get<{ success: boolean; data: MessageSummary }>(
      `/projects/${projectId}/groups/${groupId}/summary`,
      { params: { since } }
    ),

  addMember: (projectId: string, groupId: string, agentId: string) =>
    request.post<{ success: boolean }>(
      `/projects/${projectId}/groups/members`,
      {},
      { params: { group_id: groupId, agent_id: agentId } }
    ),

  removeMember: (projectId: string, groupId: string, agentId: string) =>
    request.delete<{ success: boolean }>(`/projects/${projectId}/groups/${groupId}/members/${agentId}`),

  getMembers: (projectId: string, groupId: string) =>
    request.get<{ success: boolean; data: Member[] }>(`/projects/${projectId}/groups/${groupId}/members`),

  getReadStatus: (projectId: string, groupId: string, messageId: string) =>
    request.get<{ success: boolean; data: ReadStatus }>(
      `/projects/${projectId}/groups/${groupId}/messages/${messageId}/read-status`
    ),

  markAsRead: (projectId: string, groupId: string, messageId: string, userId: string) =>
    request.post<{ success: boolean }>(
      `/projects/${projectId}/groups/${groupId}/messages/${messageId}/read`,
      {},
      { params: { user_id: userId } }
    ),

  markAllAsRead: (projectId: string, groupId: string, userId: string) =>
    request.post<{ success: boolean; data: { marked_count: number } }>(
      `/projects/${projectId}/groups/${groupId}/messages/read-all`,
      {},
      { params: { user_id: userId } }
    ),

  sendTyping: (projectId: string, groupId: string, userId: string, userName?: string) =>
    request.post<{ success: boolean }>(
      `/projects/${projectId}/groups/${groupId}/typing`,
      {},
      { params: { user_id: userId, user_name: userName } }
    ),

  getMentionedMessages: (projectId: string, groupId: string, agentId: string, params?: {
    since?: string;
    limit?: number;
  }) =>
    request.get<{ success: boolean; data: { agent_id: string; message_count: number; messages: ChatMessage[] } }>(
      `/projects/${projectId}/groups/${groupId}/messages/mentions/${agentId}`,
      { params }
    ),

  checkAgentResponse: (projectId: string, groupId: string, agentId: string, responseInterval?: number) =>
    request.post<{ success: boolean; data: { agent_id: string; should_respond: boolean } }>(
      `/projects/${projectId}/groups/${groupId}/agent/should-respond`,
      {},
      { params: { agent_id: agentId, response_interval: responseInterval } }
    ),

  parseMentions: (projectId: string, groupId: string, content: string) =>
    request.post<{
      success: boolean;
      data: { all_mentions: string[]; valid_mentions: string[]; invalid_mentions: string[] };
    }>(`/projects/${projectId}/groups/${groupId}/mentions/parse`, {}, { params: { content } }),

  summarizeChat: (projectId: string, groupId: string, data: AIRequest) =>
    request.post<{ success: boolean; data: AIResult }>(
      `/projects/${projectId}/groups/${groupId}/ai/summarize`,
      data
    ),

  suggestTasks: (projectId: string, groupId: string, data: AIRequest) =>
    request.post<{ success: boolean; data: AIResult }>(
      `/projects/${projectId}/groups/${groupId}/ai/suggest-tasks`,
      data
    ),

  decisionHelp: (projectId: string, groupId: string, data: AIRequest) =>
    request.post<{ success: boolean; data: AIResult }>(
      `/projects/${projectId}/groups/${groupId}/ai/decision-help`,
      data
    ),

  generateMeetingNotes: (projectId: string, groupId: string, data: AIRequest) =>
    request.post<{ success: boolean; data: AIResult }>(
      `/projects/${projectId}/groups/${groupId}/ai/meeting-notes`,
      data
    ),
};

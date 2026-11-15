/** 服务器档案：一台可连接的 Neurova 服务端（设计方案 §4.5） */
export interface ServerProfile {
  id: string
  name: string
  /** 直连：http(s)://host:port；中继：https://<relay>/t/<routeId> */
  baseUrl: string
  entryMode: 'direct' | 'relay'
  /** 最近成功登录的账号（仅展示，切换档案不串账号） */
  lastAccount?: string
  lastConnectedAt?: number
}

export interface TenantInfo {
  tenantId: string
  tenantName: string
}

export interface CurrentUser {
  id: string
  username: string
  email?: string
  role: string
  tenant?: TenantInfo
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  status?: 'streaming' | 'done' | 'error' | 'cancelled'
  error?: string
}

export interface ChatSessionItem {
  session_id: string
  agent_id?: string
  title?: string
  updated_at?: string
}

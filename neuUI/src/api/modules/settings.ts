import { request } from '@/api'

export type ThemeMode = 'light' | 'dark' | 'system'

export type Language = 'zh-CN' | 'en-US' | 'ja-JP'

export interface SystemSettings {
  id: string
  theme: ThemeMode
  language: Language
  timezone: string
  auto_save: boolean
  save_interval_minutes: number
  max_history_size: number
  notifications_enabled: boolean
  sound_enabled: boolean
  desktop_notifications: boolean
  privacy_mode: boolean
  data_encryption: boolean
  backup_enabled: boolean
  backup_frequency: 'daily' | 'weekly' | 'monthly'
  backup_retention_days: number
  ui_density: 'compact' | 'comfortable' | 'spacious'
  sidebar_collapsed: boolean
  workspace_layout: 'default' | 'minimal' | 'focus'
  updated_at: string
}

export interface UserPreferences {
  id: string
  user_id: string
  default_agent_id?: string
  default_workspace_id?: string
  shortcuts: Record<string, string>
  favorite_agents: string[]
  recent_chats: string[]
  ui_settings: {
    fontSize: 'small' | 'medium' | 'large'
    messageDisplay: 'compact' | 'comfortable'
    showAvatars: boolean
    showTimestamps: boolean
  }
  updated_at: string
}

export interface SecuritySettings {
  id: string
  two_factor_enabled: boolean
  session_timeout_minutes: number
  password_expiry_days?: number
  ip_whitelist?: string[]
  login_alerts: boolean
  device_management_enabled: boolean
  updated_at: string
}

export interface BackupInfo {
  id: string
  type: 'full' | 'incremental'
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  file_path: string
  file_size: number
  created_at: string
  completed_at?: string
  error_message?: string
}

export interface BackupListResponse {
  items: BackupInfo[]
  total: number
  page: number
  page_size: number
}

export const settingsAPI = {
  getSystemSettings: () =>
    request.get<SystemSettings>('/api/v1/settings/system'),

  updateSystemSettings: (data: Partial<SystemSettings>) =>
    request.put<SystemSettings>('/api/v1/settings/system', data),

  getUserPreferences: (userId: string) =>
    request.get<UserPreferences>(`/api/v1/settings/users/${userId}/preferences`),

  updateUserPreferences: (userId: string, data: Partial<UserPreferences>) =>
    request.put<UserPreferences>(`/api/v1/settings/users/${userId}/preferences`, data),

  getSecuritySettings: () =>
    request.get<SecuritySettings>('/api/v1/settings/security'),

  updateSecuritySettings: (data: Partial<SecuritySettings>) =>
    request.put<SecuritySettings>('/api/v1/settings/security', data),

  createBackup: () =>
    request.post<{ success: boolean; backup_id: string }>('/api/v1/settings/backups'),

  getBackups: (params?: { page?: number; page_size?: number }) =>
    request.get<BackupListResponse>('/api/v1/settings/backups', { params }),

  getBackup: (backupId: string) =>
    request.get<BackupInfo>(`/api/v1/settings/backups/${backupId}`),

  restoreBackup: (backupId: string) =>
    request.post<{ success: boolean }>(`/api/v1/settings/backups/${backupId}/restore`),

  deleteBackup: (backupId: string) =>
    request.delete(`/api/v1/settings/backups/${backupId}`),

  resetSettings: () =>
    request.post<{ success: boolean }>('/api/v1/settings/reset'),
}

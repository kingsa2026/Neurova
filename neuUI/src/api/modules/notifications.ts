import { request } from '@/api'

export type NotificationType = 'info' | 'success' | 'warning' | 'error' | 'system' | 'agent' | 'message' | 'task'

export type NotificationPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface Notification {
  id: string
  user_id: string
  type: NotificationType
  priority: NotificationPriority
  title: string
  content: string
  data?: Record<string, unknown>
  is_read: boolean
  read_at?: string
  is_archived: boolean
  created_at: string
  expires_at?: string
  action_url?: string
  action_text?: string
}

export interface NotificationListResponse {
  items: Notification[]
  total: number
  unread_count: number
  page: number
  page_size: number
}

export interface NotificationPreferences {
  id: string
  user_id: string
  email_enabled: boolean
  push_enabled: boolean
  desktop_enabled: boolean
  sound_enabled: boolean
  quiet_hours_enabled: boolean
  quiet_hours_start: string
  quiet_hours_end: string
  type_settings: Record<NotificationType, {
    enabled: boolean
    priority: NotificationPriority
    channels: ('email' | 'push' | 'desktop')[]
  }>
  updated_at: string
}

export interface CreateNotificationRequest {
  user_id: string
  type: NotificationType
  priority?: NotificationPriority
  title: string
  content: string
  data?: Record<string, unknown>
  expires_at?: string
  action_url?: string
  action_text?: string
}

export interface BatchMarkReadRequest {
  notification_ids: string[]
}

export interface BatchDeleteRequest {
  notification_ids: string[]
}

export const notificationsAPI = {
  getNotifications: (params?: {
    page?: number
    page_size?: number
    type?: NotificationType
    priority?: NotificationPriority
    unread_only?: boolean
    archived?: boolean
  }) =>
    request.get<NotificationListResponse>('/api/v1/notifications', { params }),

  getNotification: (notificationId: string) =>
    request.get<Notification>(`/api/v1/notifications/${notificationId}`),

  createNotification: (data: CreateNotificationRequest) =>
    request.post<Notification>('/api/v1/notifications', data),

  markAsRead: (notificationId: string) =>
    request.put<Notification>(`/api/v1/notifications/${notificationId}/read`),

  markAsUnread: (notificationId: string) =>
    request.put<Notification>(`/api/v1/notifications/${notificationId}/unread`),

  batchMarkAsRead: (data: BatchMarkReadRequest) =>
    request.post<{ success: boolean; marked_count: number }>('/api/v1/notifications/batch-read', data),

  markAllAsRead: () =>
    request.post<{ success: boolean; marked_count: number }>('/api/v1/notifications/mark-all-read'),

  archiveNotification: (notificationId: string) =>
    request.put<Notification>(`/api/v1/notifications/${notificationId}/archive`),

  unarchiveNotification: (notificationId: string) =>
    request.put<Notification>(`/api/v1/notifications/${notificationId}/unarchive`),

  deleteNotification: (notificationId: string) =>
    request.delete(`/api/v1/notifications/${notificationId}`),

  batchDeleteNotifications: (data: BatchDeleteRequest) =>
    request.post<{ success: boolean; deleted_count: number }>('/api/v1/notifications/batch-delete', data),

  getUnreadCount: () =>
    request.get<{ count: number }>('/api/v1/notifications/unread-count'),

  getPreferences: (userId: string) =>
    request.get<NotificationPreferences>(`/api/v1/notifications/users/${userId}/preferences`),

  updatePreferences: (userId: string, data: Partial<NotificationPreferences>) =>
    request.put<NotificationPreferences>(`/api/v1/notifications/users/${userId}/preferences`, data),

  clearArchived: () =>
    request.delete<{ success: boolean; deleted_count: number }>('/api/v1/notifications/clear-archived'),
}

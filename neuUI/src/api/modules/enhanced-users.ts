import { request } from '@/api';

export interface EnhancedUser {
  user_id: string | number;
  username: string;
  email: string;
  group_type: string;
  status: string;
  created_at: string;
  last_login?: string;
  language?: string;
  timezone?: string;
  theme?: string;
  notifications?: boolean;
}

export interface UserDetail extends EnhancedUser {
  quota_status?: Record<string, unknown>;
}

export interface UserCreate {
  username: string;
  email: string;
  password: string;
  group_type: string;
}

export interface UserUpdate {
  username?: string;
  email?: string;
  password?: string;
  group_type?: string;
  status?: string;
  language?: string;
  timezone?: string;
  theme?: string;
  notifications?: boolean;
}

export interface PasswordChange {
  old_password: string;
  new_password: string;
}

export interface UserQuotaStatus {
  quota: Record<string, unknown>;
  usage: Record<string, unknown>;
  remaining: Record<string, unknown>;
}

export interface UserBackup {
  backup_id: string;
  user_id: string | number;
  username: string;
  backup_at: string;
  backup_size: number;
  summary: string;
}

export const enhancedUserAPI = {
  list: (params?: {
    group_type?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => request.get<EnhancedUser[]>('/settings/users', { params }),

  get: (userId: string | number) => request.get<UserDetail>(`/settings/users/${userId}`),

  create: (data: UserCreate) => request.post('/settings/users', data),

  update: (userId: string | number, data: UserUpdate) =>
    request.put(`/settings/users/${userId}`, data),

  delete: (userId: string | number, backupBeforeDelete: boolean = true) =>
    request.delete(`/settings/users/${userId}`, { params: { backup_before_delete: backupBeforeDelete } }),

  backup: (userId: string | number) =>
    request.post(`/settings/users/${userId}/backup`),

  getQuota: (userId?: string | number) => {
    if (userId) {
      return request.get<UserQuotaStatus>(`/settings/users/${userId}/quota`);
    }
    return request.get<UserQuotaStatus>('/settings/users/quota');
  },

  changePassword: (data: PasswordChange) =>
    request.post('/settings/users/change-password', data),

  listBackups: (userId?: string | number) =>
    request.get<UserBackup[]>('/settings/users/backups', { params: { user_id: userId } }),

  restoreUser: (backupId: string) =>
    request.post(`/settings/users/backups/${backupId}/restore`),

  deleteBackup: (backupId: string) =>
    request.delete(`/settings/users/backups/${backupId}`),
};

import { request } from '@/api';

export interface FileInfo {
  id: string;
  name: string;
  type: string;
  mime_type?: string;
  size: number;
  status: string;
  preview_url?: string;
  download_url?: string;
  created_at: string;
  download_count?: number;
  metadata?: {
    description?: string;
    uploader?: string;
    user_id?: string;
    agent_id?: string;
    session_id?: string;
  };
}

export const filesAPI = {
  // 获取Agent文件列表
  list: (agentId?: string, sessionId?: string, fileType?: string) =>
    request.get<{ data: FileInfo[] }>('/files', {
      params: { agent_id: agentId, session_id: sessionId, file_type: fileType },
    }),

  // 上传文件
  upload: (agentId?: string, sessionId?: string, file?: File, description?: string, requireApproval?: boolean) => {
    const formData = new FormData();
    if (file) formData.append('file', file);
    if (description) formData.append('description', description);
    if (requireApproval !== undefined) formData.append('require_approval', String(requireApproval));
    if (agentId) formData.append('agent_id', agentId);
    if (sessionId) formData.append('session_id', sessionId);

    return request.post<{ data: FileInfo }>('/files/upload', formData);
  },

  // 删除文件
  delete: (fileId: string) => request.delete<{ success: boolean; message?: string }>(`/files/${fileId}`),

  // 获取文件信息
  getInfo: (fileId: string) => request.get<{ data: FileInfo }>(`/files/${fileId}/info`),

  // 更新文件信息
  update: (fileId: string, data: { name?: string; description?: string; type?: string }) =>
    request.put<{ data: { id: string; name: string; description?: string; type: string } }>(`/files/${fileId}`, data),

  // 下载/预览文件
  download: (fileId: string) =>
    request.get(`/files/${fileId}/download`, { responseType: 'blob' }),

  preview: (fileId: string) =>
    request.get(`/files/${fileId}/preview`, { responseType: 'blob' }),

  // 版本管理
  getVersions: (fileId: string) =>
    request.get<{ data: Record<string, unknown>[] }>(`/files/${fileId}/versions`),

  downloadVersion: (fileId: string, version: string) =>
    request.get(`/files/${fileId}/versions/${version}/download`, { responseType: 'blob' }),

  // 审批流程
  approve: (fileId: string) =>
    request.post<{ data: { id: string; status: string } }>(`/files/${fileId}/approve`),

  reject: (fileId: string, reason?: string) =>
    request.post<{ data: { id: string; status: string } }>(`/files/${fileId}/reject`, { reason }),

  // 存储信息
  getStorageInfo: () =>
    request.get<{
      data: {
        user_id: string;
        total_size: number;
        total_files: number;
        type_stats: Record<string, { count: number; size: number }>;
        storage_path: string;
      };
    }>('/files/storage/info'),

  cleanup: (days?: number) =>
    request.post<{ success: boolean; message?: string }>('/files/cleanup', { days }),
};

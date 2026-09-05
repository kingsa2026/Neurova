import { request } from '@/api';

/**
 * 知识库配置 API
 */
export interface KnowledgeConfig {
  id: string;
  source_type: string;
  config_name: string;
  api_key?: string;
  base_url?: string;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export const knowledgeAPI = {
  // 配置管理
  getConfigs: () => request.get<{ configs: KnowledgeConfig[] }>('/knowledge/configs'),
  createConfig: (data: {
    source_type: string;
    config_name: string;
    api_key: string;
    base_url?: string;
    is_default?: boolean;
  }) => request.post<{
    id: string;
    source_type: string;
    config_name: string;
    api_key?: string;
    base_url?: string;
    is_default: boolean;
    is_active: boolean;
    created_at: string;
  }>('/knowledge/configs', data),
  updateConfig: (configId: string, data: {
    api_key?: string;
    config_name?: string;
    base_url?: string;
    is_default?: boolean;
    is_active?: boolean;
  }) => request.put(`/knowledge/configs/${configId}`, data),
  deleteConfig: (configId: string) => request.delete(`/knowledge/configs/${configId}`),

  // 知识库集合
  getCollections: () => request.get<{ collections: Record<string, unknown>[]; total: number }>('/knowledge/collections'),
  createCollection: (data: { name: string; description: string }) => request.post<{
    id: string;
    name: string;
    description: string;
  }>('/knowledge/collections', data),
  getCollection: (collectionId: string) => request.get(`/knowledge/collections/${collectionId}`),
  updateCollection: (collectionId: string, data: { name?: string; description?: string }) =>
    request.put(`/knowledge/collections/${collectionId}`, data),
  deleteCollection: (collectionId: string) => request.delete(`/knowledge/collections/${collectionId}`),

  // 文档管理
  uploadDocument: (formData: FormData) =>
    request.post<{ id: string; name: string; collection_id: string }>('/knowledge/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }),
  getDocuments: (collectionId: string, page?: number, pageSize?: number, keyword?: string) =>
    request.get<{ documents: Record<string, unknown>[]; total: number }>(`/knowledge/collections/${collectionId}/documents`, {
      params: { page, page_size: pageSize, keyword },
    }),
  deleteDocument: (documentId: string) => request.delete(`/knowledge/documents/${documentId}`),

  // 搜索
  search: (query: string, collectionId?: string, limit?: number) =>
    request.post<{ items: Record<string, unknown>[]; total: number; query: string }>('/knowledge/search', {
      query,
      collection_id: collectionId,
      limit,
    }),
  searchMulti: (query: string, collectionIds?: string[], limitPerCollection?: number) =>
    request.post<{ items: Record<string, unknown>[]; total: number; query: string }>('/knowledge/search/multi', {
      query,
      collection_id: collectionIds?.[0],
    }),
};

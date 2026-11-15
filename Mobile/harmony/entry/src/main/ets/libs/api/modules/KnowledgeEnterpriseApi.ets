/**
 * KnowledgeEnterpriseApi - 企业数据源 API 模块（同源 PC EnterpriseSourcesPage）
 *
 * 后端事实源：neurova/api/endpoints/knowledge_enterprise.py（经 knowledge.py 挂 /v1/knowledge）：
 *   GET  /knowledge/enterprise/sources           → {code:0,data:{items:[_view],total}}
 *   GET  /knowledge/enterprise/sources/{id}/health → 连接健康探测（仅管理员，403 门控）
 * _view 投影：{source_id, descriptor{}, cursor, enabled, adapter_registered,
 *              created_at, updated_at, ingested_count}
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 企业源条目（_view 投影） */
export interface EnterpriseSourceDto {
  source_id: string;
  descriptor: Record<string, Object>;
  cursor: string;
  enabled: boolean;
  adapter_registered: boolean;
  created_at: string;
  updated_at: string;
  ingested_count: number;
}

/** 列表载荷 */
export interface EnterpriseSourceList {
  items: EnterpriseSourceDto[];
  total: number;
}

export class KnowledgeEnterpriseApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 已提交源列表（登录可读） */
  async listSources(): Promise<ApiResponse<EnterpriseSourceList>> {
    return this.client.get<EnterpriseSourceList>('/knowledge/enterprise/sources');
  }

  /** 连接健康探测（仅管理员，非管理员 403） */
  async health(sourceId: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {};
    return this.client.post<Object>(`/knowledge/enterprise/sources/${sourceId}/health`, body);
  }
}

/**
 * KnowledgeApi - 知识库 API 模块（同源 PC KnowledgePage，端点经后端源码核对）
 *
 * 后端事实源：neurova/api/endpoints/knowledge_core.py + knowledge_sharing.py
 * （聚合挂载于 /v1/knowledge）：
 *   GET    /knowledge?scope=&page=&page_size=   三库分类列表（public/private/shared），
 *          信封 {code:0,data:{items,total,page,page_size}}，条目为 item_response 投影
 *   POST   /knowledge/search {query,limit}      → **裸数组** [item_response]
 *   POST   /knowledge/{id}/submit-public        → 提交公共库
 *   POST   /knowledge/{id}/share {usernames[]}  → 共享给他人（按用户名解析）
 *   POST   /knowledge/{id}/unshare {usernames[]}
 *   POST   /knowledge       创建（KnowledgeCreate）
 *   PUT/DELETE /knowledge/{id}
 *
 * 时间戳口径：后端 item_response 的 created_at/updated_at 是**秒级** Unix 时间戳
 * （knowledge_core.py `datetime.timestamp()` 产出）；JS Date 构造只吃毫秒，
 * 直接透传会渲染成 1970 年——映射处统一 ×1000。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse, KnowledgeItem, PageResult } from '../../types';

/** 后端条目投影（item_response，字段名为后端 snake_case 原样） */
export interface KnowledgeItemDto {
  knowledge_id: string;
  title: string;
  content: string;
  category: string;
  tags: string[];
  source: string;
  confidence: number;
  created_at: number;
  updated_at: number;
  visibility: string;
  owner_user_id: string;
  shared_with: string[];
}

/** 列表信封载荷 */
export interface KnowledgeListPayload {
  items: KnowledgeItemDto[];
  total: number;
  page: number;
  page_size: number;
}

/** 列表查询参数 */
export interface KnowledgeListQuery {
  scope?: string;      // all / public / private / shared
  category?: string;
  agentId?: string;
  page?: number;
  pageSize?: number;
}

export class KnowledgeApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 后端条目 → 前端 KnowledgeItem（单源映射） */
  private static toItem(dto: KnowledgeItemDto): KnowledgeItem {
    const item: KnowledgeItem = {
      id: dto.knowledge_id,
      title: dto.title,
      content: dto.content,
      source: dto.source,
      category: dto.category,
      tags: dto.tags,
      status: 'ready',
      createdAt: dto.created_at > 0 ? new Date(dto.created_at * 1000).toISOString() : '',
      updatedAt: dto.updated_at > 0 ? new Date(dto.updated_at * 1000).toISOString() : '',
      visibility: dto.visibility,
      ownerUserId: dto.owner_user_id,
      sharedWith: dto.shared_with,
    };
    return item;
  }

  /** 三库分类列表（scope：all/public/private/shared） */
  async listScoped(query: KnowledgeListQuery): Promise<ApiResponse<PageResult<KnowledgeItem>>> {
    const qs: string[] = [];
    if (query.scope && query.scope !== 'all') {
      qs.push('scope=' + encodeURIComponent(query.scope));
    }
    if (query.category && query.category.length > 0) {
      qs.push('category=' + encodeURIComponent(query.category));
    }
    if (query.agentId && query.agentId.length > 0) {
      qs.push('agent_id=' + encodeURIComponent(query.agentId));
    }
    qs.push('page=' + (query.page !== undefined ? query.page : 1).toString());
    qs.push('page_size=' + (query.pageSize !== undefined ? query.pageSize : 50).toString());
    const res = await this.client.get<KnowledgeListPayload>('/knowledge?' + qs.join('&'));
    if (res.code === 0 && res.data) {
      const items: KnowledgeItem[] = [];
      for (const dto of res.data.items) {
        items.push(KnowledgeApi.toItem(dto));
      }
      const page: PageResult<KnowledgeItem> = {
        items: items,
        total: res.data.total,
        page: res.data.page,
        size: res.data.page_size,
      };
      const mapped: ApiResponse<PageResult<KnowledgeItem>> = {
        code: res.code,
        message: res.message,
        data: page,
      };
      return mapped;
    }
    const empty: PageResult<KnowledgeItem> = { items: [], total: 0, page: 1, size: 0 };
    const fallback: ApiResponse<PageResult<KnowledgeItem>> = {
      code: res.code,
      message: res.message,
      data: empty,
    };
    return fallback;
  }

  /** 搜索（POST /knowledge/search {query,limit}，裸数组返回） */
  async search(query: string, limit?: number): Promise<KnowledgeItem[]> {
    const body: Record<string, Object> = {
      'query': query,
      'limit': limit !== undefined ? limit : 20,
    };
    const res = await this.client.post<KnowledgeItem[]>('/knowledge/search', body);
    const arr = res as Object as KnowledgeItemDto[];
    const out: KnowledgeItem[] = [];
    for (const dto of arr) {
      out.push(KnowledgeApi.toItem(dto));
    }
    return out;
  }

  /** 提交公共库 */
  async submitPublic(knowledgeId: string): Promise<ApiResponse<KnowledgeItem>> {
    const body: Record<string, Object> = {};
    return this.client.post<KnowledgeItem>(`/knowledge/${knowledgeId}/submit-public`, body);
  }

  /** 共享给他人（按用户名列表） */
  async share(knowledgeId: string, usernames: string[]): Promise<ApiResponse<KnowledgeItem>> {
    const body: Record<string, Object> = { 'usernames': usernames };
    return this.client.post<KnowledgeItem>(`/knowledge/${knowledgeId}/share`, body);
  }

  /** 收回共享 */
  async unshare(knowledgeId: string, usernames: string[]): Promise<ApiResponse<KnowledgeItem>> {
    const body: Record<string, Object> = { 'usernames': usernames };
    return this.client.post<KnowledgeItem>(`/knowledge/${knowledgeId}/unshare`, body);
  }

  /** 获取单条知识 */
  async get(knowledgeId: string): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.get<KnowledgeItem>(`/knowledge/${knowledgeId}`);
  }

  /** 创建知识 */
  async create(data: Partial<KnowledgeItem>): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.post<KnowledgeItem>('/knowledge', data);
  }

  /** 更新知识 */
  async update(knowledgeId: string, data: Partial<KnowledgeItem>): Promise<ApiResponse<KnowledgeItem>> {
    return this.client.put<KnowledgeItem>(`/knowledge/${knowledgeId}`, data);
  }

  /** 删除知识 */
  async remove(knowledgeId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/knowledge/${knowledgeId}`);
  }

  /** URL 导入（knowledge_ingestion.py /import-url，query 传参；sync=true 同步抽取） */
  async importUrl(url: string, agentId?: string, category?: string): Promise<ApiResponse<Object>> {
    const qs: string[] = [];
    qs.push('url=' + encodeURIComponent(url));
    qs.push('agent_id=' + encodeURIComponent(agentId && agentId.length > 0 ? agentId : 'default'));
    qs.push('sync=true');
    if (category && category.length > 0) {
      qs.push('category=' + encodeURIComponent(category));
    }
    const body: Record<string, Object> = {};
    return this.client.post<Object>('/knowledge/import-url?' + qs.join('&'), body);
  }
}

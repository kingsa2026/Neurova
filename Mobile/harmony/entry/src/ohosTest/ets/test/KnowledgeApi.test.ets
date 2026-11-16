// KnowledgeApi 单元测试 - TDD 垂直切片
// 验证 KnowledgeApi 调用契约：method/url/body/返回值
//
// 契约基准（R2 对齐真实实现，替代旧 legacy 视图用例）：
//   listScoped(query) → GET /knowledge?scope=&category=&agent_id=&page=&page_size=
//     信封 {code:0,data:{items,total,page,page_size}}，条目为 item_response 投影
//     （created_at/updated_at 为**秒级** Unix 时间戳，映射 ×1000——审计 3.8-1）
//   search(query, limit?) → POST /knowledge/search {query,limit}，**裸数组**返回
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse, KnowledgeItem, PageResult } from '../../../main/ets/libs/types';
import {
  KnowledgeApi, KnowledgeListQuery, KnowledgeItemDto, KnowledgeListPayload,
} from '../../../main/ets/libs/api/modules/KnowledgeApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 造一条后端 item_response 投影（knowledge_core.py 字段，时间为秒级时间戳） */
function makeDto(id: string, title: string, createdAtSeconds: number): KnowledgeItemDto {
  const dto: KnowledgeItemDto = {
    knowledge_id: id,
    title: title,
    content: 'c',
    category: 'general',
    tags: [],
    source: 'manual',
    confidence: 1.0,
    created_at: createdAtSeconds,
    updated_at: createdAtSeconds,
    visibility: 'private',
    owner_user_id: 'u1',
    shared_with: [],
  };
  return dto;
}

// Mock 后端实现（参考 HttpClient.test.ets 模式）
class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: new Object() };

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.response };
    return resp;
  }
}

export default function knowledgeApiTest() {
  describe('KnowledgeApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: KnowledgeApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new KnowledgeApi(client);
    });

    // ========== 行为 1: listScoped - GET /knowledge（默认分页） ==========
    it('listScoped_calls_knowledge_url_with_default_paging', 0, async () => {
      const payload: KnowledgeListPayload = { items: [], total: 0, page: 1, page_size: 50 };
      backend.response = { code: 0, message: 'ok', data: payload };
      const query: KnowledgeListQuery = {};
      await api.listScoped(query);
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge?page=1&page_size=50');
    });

    it('listScoped_passes_real_filter_params', 0, async () => {
      const payload: KnowledgeListPayload = { items: [], total: 0, page: 2, page_size: 5 };
      backend.response = { code: 0, message: 'ok', data: payload };
      const query: KnowledgeListQuery = { scope: 'public', category: 'tech', agentId: 'a1', page: 2, pageSize: 5 };
      await api.listScoped(query);
      const url = backend.requests[0].url;
      expect(url.includes('scope=public')).assertTrue();
      expect(url.includes('category=tech')).assertTrue();
      expect(url.includes('agent_id=a1')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('page_size=5')).assertTrue();
    });

    // ========== 行为 2: listScoped 映射 + 秒级时间戳 ×1000 ==========
    it('listScoped_maps_items_and_converts_seconds_timestamps', 0, async () => {
      const payload: KnowledgeListPayload = {
        items: [makeDto('k1', 't', 1763220000)],
        total: 1,
        page: 1,
        page_size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: payload };
      const query: KnowledgeListQuery = {};
      const res = await api.listScoped(query);
      expect(res.code).assertEqual(0);
      const page: PageResult<KnowledgeItem> = res.data!;
      expect(page.total).assertEqual(1);
      expect(page.size).assertEqual(20);
      expect(page.items[0].id).assertEqual('k1');
      // 秒级 1763220000 → 2025-11-15（若按毫秒误读则是 1970-01）
      const year = new Date(page.items[0].createdAt).getUTCFullYear();
      expect(year).assertEqual(2025);
    });

    // ========== 行为 3: get ==========
    it('get_calls_get_with_id', 0, () => {
      api.get('k1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge/k1');
    });

    // ========== 行为 4: create ==========
    it('create_posts_body_to_knowledge', 0, () => {
      const data: Partial<KnowledgeItem> = { title: 't', content: 'c', source: 'manual' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 5: update ==========
    it('update_puts_to_id_url', 0, () => {
      const data: Partial<KnowledgeItem> = { title: 'updated' };
      api.update('k1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge/k1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 6: remove ==========
    it('remove_deletes_by_id', 0, () => {
      api.remove('k1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge/k1');
    });

    // ========== 行为 7: search - POST /knowledge/search {query,limit} ==========
    it('search_posts_query_and_limit_body', 0, async () => {
      const dto = makeDto('k1', 't', 1763220000);
      backend.response = { code: 0, message: 'ok', data: [dto] as Object };
      const hits = await api.search('关键词', 10);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/knowledge/search');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['query']).assertEqual('关键词');
      expect(body['limit']).assertEqual(10);
      // 裸数组返回 → 映射为 KnowledgeItem[]（非 ApiResponse 信封）
      expect(hits.length).assertEqual(1);
      expect(hits[0].id).assertEqual('k1');
      const year = new Date(hits[0].createdAt).getUTCFullYear();
      expect(year).assertEqual(2025);
    });

    it('search_defaults_limit_20', 0, async () => {
      const dto = makeDto('k2', 't2', 1763220000);
      backend.response = { code: 0, message: 'ok', data: [dto] as Object };
      await api.search('hit');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['query']).assertEqual('hit');
      expect(body['limit']).assertEqual(20);
    });
  });
}

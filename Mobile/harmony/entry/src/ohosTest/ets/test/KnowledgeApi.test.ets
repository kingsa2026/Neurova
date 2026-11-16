// KnowledgeApi 单元测试 - TDD 垂直切片
// 验证 KnowledgeApi 调用契约：method/url/body/返回值
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse, KnowledgeItem, KnowledgeQuery, KnowledgeStatus, PageResult } from '../../../main/ets/libs/types';
import { KnowledgeApi } from '../../../main/ets/libs/api/modules/KnowledgeApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/**
 * 旧契约视图：主源码 KnowledgeApi 已根修——list 收口为 listScoped(query)
 * （/knowledge?scope/page/page_size），search 收口为 (query, limit) 裸数组返回。
 * 本文件按任务要求保留旧端点断言原文，仅经此视图做编译期类型衔接；
 * 运行期对应方法已不存在（契约已过时，见测试报告）。
 */
interface KnowledgeApiLegacy {
  list(query?: KnowledgeQuery): Promise<ApiResponse<PageResult<KnowledgeItem>>>;
  search(keyword: string, agentId?: string, limit?: number): Promise<ApiResponse<KnowledgeItem[]>>;
}

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

    // ========== 行为 1: list - GET /v1/knowledge ==========
    it('list_calls_get_knowledge_url', 0, () => {
      const page: PageResult<KnowledgeItem> = { items: [], total: 0, page: 1, size: 20 };
      backend.response = { code: 0, message: 'ok', data: page };
      const legacy = api as Object as KnowledgeApiLegacy;
      legacy.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge');
    });

    it('list_serializes_query_object', 0, () => {
      const page: PageResult<KnowledgeItem> = { items: [], total: 0, page: 1, size: 20 };
      backend.response = { code: 0, message: 'ok', data: page };
      const query: KnowledgeQuery = { keyword: 'ai', agentId: 'a1', page: 1, size: 5 };
      const legacy = api as Object as KnowledgeApiLegacy;
      legacy.list(query);
      const url = backend.requests[0].url;
      expect(url.includes('keyword=ai')).assertTrue();
      expect(url.includes('agentId=a1')).assertTrue();
      expect(url.includes('page=1')).assertTrue();
      expect(url.includes('size=5')).assertTrue();
    });

    it('list_returns_page_result', 0, () => {
      const page: PageResult<KnowledgeItem> = {
        items: [{
          id: 'k1', title: 't', content: 'c', source: 'manual',
          status: 'ready' as KnowledgeStatus, createdAt: '', updatedAt: '',
        }],
        total: 1, page: 1, size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: page };
      let resolved: ApiResponse<PageResult<KnowledgeItem>> | null = null;
      const legacy = api as Object as KnowledgeApiLegacy;
      legacy.list().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.items[0].id).assertEqual('k1');
      }, 10);
    });

    // ========== 行为 2: get ==========
    it('get_calls_get_with_id', 0, () => {
      api.get('k1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge/k1');
    });

    // ========== 行为 3: create ==========
    it('create_posts_body_to_knowledge', 0, () => {
      const data: Partial<KnowledgeItem> = { title: 't', content: 'c', source: 'manual' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 4: update ==========
    it('update_puts_to_id_url', 0, () => {
      const data: Partial<KnowledgeItem> = { title: 'updated' };
      api.update('k1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge/k1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 5: remove ==========
    it('remove_deletes_by_id', 0, () => {
      api.remove('k1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge/k1');
    });

    // ========== 行为 6: search ==========
    it('search_posts_keyword_to_search_endpoint', 0, () => {
      const legacy = api as Object as KnowledgeApiLegacy;
      legacy.search('关键词', 'a1', 10);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/knowledge/search');
      expect(backend.requests[0].body).assertEqual({ keyword: '关键词', agentId: 'a1', limit: 10 });
    });

    it('search_returns_knowledge_array', 0, () => {
      const results: KnowledgeItem[] = [{
        id: 'k1', title: 't', content: 'c', source: 'manual',
        status: 'ready' as KnowledgeStatus, createdAt: '', updatedAt: '',
      }];
      backend.response = { code: 0, message: 'ok', data: results };
      let resolved: ApiResponse<KnowledgeItem[]> | null = null;
      const legacy = api as Object as KnowledgeApiLegacy;
      legacy.search('t').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.length).assertEqual(1);
      }, 10);
    });
  });
}

// MemoryApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 MemoryApi 调用契约（method/url/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse, Memory, MemoryType, PageResult } from '../../../../main/ets/libs/types';
import { MemoryApi } from '../../../../main/ets/libs/api/modules/MemoryApi';

// Mock 后端实现（参考 HttpClient.test.ets 模式）
class MockBackend implements HttpBackend {
  public requests: { method: string; url: string; body: Object | null }[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    this.requests.push({ method, url, body });
    return { status: 200, data: this.response };
  }
}

export default function memoryApiTest() {
  describe('MemoryApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: MemoryApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new MemoryApi(client);
    });

    // ========== 行为 1: list - GET /v1/memory ==========
    it('list_calls_get_with_correct_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory');
    });

    it('list_passes_query_params', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.list('agent-1', 'episodic' as MemoryType, { page: 2, size: 10 });
      const url = backend.requests[0].url;
      expect(url.includes('agentId=agent-1')).assertTrue();
      expect(url.includes('type=episodic')).assertTrue();
      expect(url.includes('page=2')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('list_returns_page_result', 0, () => {
      const page: PageResult<Memory> = {
        items: [{ id: 'm1', type: 'episodic', content: 'hello', agentId: 'a1', createdAt: '', updatedAt: '' }],
        total: 1, page: 1, size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: page };
      let resolved: ApiResponse<PageResult<Memory>> | null = null;
      api.list().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.total).assertEqual(1);
        expect(resolved!.data.items[0].id).assertEqual('m1');
      }, 10);
    });

    // ========== 行为 2: get - GET /v1/memory/{id} ==========
    it('get_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', type: 'episodic', content: 'c', agentId: 'a1', createdAt: '', updatedAt: '' } };
      api.get('m1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory/m1');
    });

    // ========== 行为 3: create - POST /v1/memory ==========
    it('create_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', type: 'episodic', content: 'c', agentId: 'a1', createdAt: '', updatedAt: '' } };
      const data: Partial<Memory> = { type: 'episodic', content: 'memory content', agentId: 'a1' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 4: update - PUT /v1/memory/{id} ==========
    it('update_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', type: 'episodic', content: 'updated', agentId: 'a1', createdAt: '', updatedAt: '' } };
      const data: Partial<Memory> = { content: 'updated' };
      api.update('m1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory/m1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 5: remove - DELETE /v1/memory/{id} ==========
    it('remove_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.remove('m1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory/m1');
    });

    // ========== 行为 6: search - POST /v1/memory/search ==========
    it('search_calls_post_search_endpoint', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.search({ keyword: 'hello', agentId: 'a1', limit: 5 });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/memory/search');
      expect(backend.requests[0].body).assertEqual({ agentId: 'a1', keyword: 'hello', limit: 5 });
    });

    it('search_returns_memory_array', 0, () => {
      const results: Memory[] = [
        { id: 'm1', type: 'episodic', content: 'hit', agentId: 'a1', createdAt: '', updatedAt: '' },
      ];
      backend.response = { code: 0, message: 'ok', data: results };
      let resolved: ApiResponse<Memory[]> | null = null;
      api.search({ keyword: 'hit' }).then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.length).assertEqual(1);
        expect(resolved!.data[0].id).assertEqual('m1');
      }, 10);
    });
  });
}

// MemoryApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 MemoryApi 调用契约（method/url/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
//
// 契约基准（R2 对齐真实实现，替代旧 legacy 视图用例）：
//   list(agentId?, type?, limit?, query?) → GET /memory?agent_id=&memory_type=&limit=
//     （查询即搜索：query 走同一端点的 query= 参数，无独立 /search 端点）
//   后端 data 形状 {count, memories:[MemoryItemDto]}，映射为 PageResult<Memory>
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse, Memory, MemoryType, PageResult } from '../../../main/ets/libs/types';
import { MemoryApi, MemoryListPayload, MemoryItemDto } from '../../../main/ets/libs/api/modules/MemoryApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 造一条后端 MemoryItemDto（crud.py memory_to_dict 投影字段） */
function makeDto(id: string, content: string): MemoryItemDto {
  const dto: MemoryItemDto = {
    id: id,
    agent_id: 'a1',
    content: content,
    category: 'general',
    type: 'episodic',
    temperature: 0.5,
    importance: 0.5,
    tags: [],
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

    // ========== 行为 1: list - GET /memory（默认 limit=50） ==========
    it('list_calls_get_with_correct_url', 0, () => {
      const payload: MemoryListPayload = { count: 0, memories: [] };
      backend.response = { code: 0, message: 'ok', data: payload };
      api.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory?limit=50');
    });

    it('list_passes_real_query_params', 0, () => {
      const payload: MemoryListPayload = { count: 0, memories: [] };
      backend.response = { code: 0, message: 'ok', data: payload };
      api.list('agent-1', 'episodic' as MemoryType, 10);
      const url = backend.requests[0].url;
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('memory_type=episodic')).assertTrue();
      expect(url.includes('limit=10')).assertTrue();
    });

    it('list_maps_count_memories_to_page_result', 0, () => {
      const payload: MemoryListPayload = { count: 1, memories: [makeDto('m1', 'hello')] };
      backend.response = { code: 0, message: 'ok', data: payload };
      let resolved: ApiResponse<PageResult<Memory>> | null = null;
      api.list().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.total).assertEqual(1);
        expect(resolved!.data.items[0].id).assertEqual('m1');
        expect(resolved!.data.items[0].agentId).assertEqual('a1');
      }, 10);
    });

    // ========== 行为 2: 搜索即 list+query（无独立 /search 端点） ==========
    it('search_via_list_query_param', 0, () => {
      const payload: MemoryListPayload = { count: 0, memories: [] };
      backend.response = { code: 0, message: 'ok', data: payload };
      api.list(undefined, undefined, 5, 'hello');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory?query=hello&limit=5');
    });

    // ========== 行为 3: get - GET /memory/{id} ==========
    it('get_calls_get_with_id_in_url', 0, () => {
      const memory: Memory = { id: 'm1', type: 'episodic', content: 'c', agentId: 'a1', createdAt: '', updatedAt: '' };
      backend.response = { code: 0, message: 'ok', data: memory };
      api.get('m1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory/m1');
    });

    // ========== 行为 4: create - POST /memory ==========
    it('create_calls_post_with_body', 0, () => {
      const memory: Memory = { id: 'm1', type: 'episodic', content: 'c', agentId: 'a1', createdAt: '', updatedAt: '' };
      backend.response = { code: 0, message: 'ok', data: memory };
      const data: Partial<Memory> = { type: 'episodic', content: 'memory content', agentId: 'a1' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 5: update - PUT /memory/{id} ==========
    it('update_calls_put_with_id_and_body', 0, () => {
      const memory: Memory = { id: 'm1', type: 'episodic', content: 'updated', agentId: 'a1', createdAt: '', updatedAt: '' };
      backend.response = { code: 0, message: 'ok', data: memory };
      const data: Partial<Memory> = { content: 'updated' };
      api.update('m1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory/m1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== 行为 6: remove - DELETE /memory/{id} ==========
    it('remove_calls_delete_with_id', 0, () => {
      const empty: Record<string, Object> = {};
      backend.response = { code: 0, message: 'ok', data: empty };
      api.remove('m1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/memory/m1');
    });
  });
}

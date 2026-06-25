// CapabilityApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 CapabilityApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  PageResult,
  Rule,
  AgentFile,
  MediaAsset,
} from '../../../../main/ets/libs/types';
import { CapabilityApi } from '../../../../main/ets/libs/api/modules/CapabilityApi';

// Mock 后端实现（参考 MemoryApi.test.ets 模式）
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

export default function capabilityApiTest() {
  describe('CapabilityApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: CapabilityApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new CapabilityApi(client);
    });

    // ========== Rule: list/create/update ==========
    it('listRules_calls_get_with_agentId_and_paging', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listRules('agent-1', { page: 1, size: 10 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/v1/capability/rules')).assertTrue();
      expect(url.includes('agentId=agent-1')).assertTrue();
      expect(url.includes('page=1')).assertTrue();
      expect(url.includes('size=10')).assertTrue();
    });

    it('createRule_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'r1', agentId: 'a1', name: 'n', type: 'permission', status: 'active', priority: 1, condition: 'c', action: 'a', createdAt: '', updatedAt: '' } };
      const data: Partial<Rule> = { agentId: 'a1', name: 'n', type: 'permission', condition: 'c', action: 'a', priority: 1 };
      api.createRule(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/rules');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('updateRule_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'r1', agentId: 'a1', name: 'n2', type: 'permission', status: 'active', priority: 1, condition: 'c', action: 'a', createdAt: '', updatedAt: '' } };
      const data: Partial<Rule> = { name: 'n2' };
      api.updateRule('r1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/rules/r1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== AgentFile: get/create/remove ==========
    it('getFile_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'f1', agentId: 'a1', name: 'n', path: '/p', size: 100, mimeType: 'text/plain', uploadedAt: '' } };
      api.getFile('f1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/files/f1');
    });

    it('createFile_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'f1', agentId: 'a1', name: 'n', path: '/p', size: 100, mimeType: 'text/plain', uploadedAt: '' } };
      const data: Partial<AgentFile> = { agentId: 'a1', name: 'n', path: '/p', size: 100, mimeType: 'text/plain' };
      api.createFile(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/files');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('removeFile_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeFile('f1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/files/f1');
    });

    // ========== MediaAsset: list/get/update ==========
    it('listMedia_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listMedia('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/capability/media')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('getMedia_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', agentId: 'a1', type: 'image', name: 'n', url: '/u', size: 100, createdAt: '' } };
      api.getMedia('m1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/media/m1');
    });

    it('updateMedia_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'm1', agentId: 'a1', type: 'image', name: 'n2', url: '/u', size: 100, createdAt: '' } };
      const data: Partial<MediaAsset> = { name: 'n2' };
      api.updateMedia('m1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/capability/media/m1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('listRules_returns_page_result', 0, () => {
      const page: PageResult<Rule> = {
        items: [{ id: 'r1', agentId: 'a1', name: 'n', type: 'permission', status: 'active', priority: 1, condition: 'c', action: 'a', createdAt: '', updatedAt: '' }],
        total: 1, page: 1, size: 20,
      };
      backend.response = { code: 0, message: 'ok', data: page };
      let resolved: ApiResponse<PageResult<Rule>> | null = null;
      api.listRules('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.total).assertEqual(1);
        expect(resolved!.data.items[0].id).assertEqual('r1');
      }, 10);
    });
  });
}

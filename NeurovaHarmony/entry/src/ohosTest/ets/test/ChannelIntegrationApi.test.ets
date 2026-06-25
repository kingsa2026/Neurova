// ChannelIntegrationApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 ChannelIntegrationApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  PageResult,
  ChannelIntegration,
} from '../../../../main/ets/libs/types';
import { ChannelIntegrationApi } from '../../../../main/ets/libs/api/modules/ChannelIntegrationApi';

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

export default function channelIntegrationApiTest() {
  describe('ChannelIntegrationApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: ChannelIntegrationApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new ChannelIntegrationApi(client);
    });

    // ========== list ==========
    it('list_calls_get_with_agentId_and_paging', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.list('agent-1', { page: 1, size: 10 });
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/channel-integrations')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
      expect(backend.requests[0].url.includes('page=1')).assertTrue();
      expect(backend.requests[0].url.includes('size=10')).assertTrue();
    });

    it('list_calls_get_with_status_filter', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.list('agent-1', { status: 'connected' });
      expect(backend.requests[0].url.includes('status=connected')).assertTrue();
    });

    // ========== get ==========
    it('get_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ci-1', channelId: 'c1', type: 'feishu', name: 'n', status: 'connected', capabilities: [] } };
      api.get('ci-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/channel-integrations/ci-1');
    });

    // ========== create ==========
    it('create_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ci-1', channelId: 'c1', type: 'feishu', name: 'n', status: 'connected', capabilities: [] } };
      const data: Partial<ChannelIntegration> = { channelId: 'c1', type: 'feishu', name: 'n' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/channel-integrations');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== update ==========
    it('update_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ci-1', channelId: 'c1', type: 'feishu', name: 'n2', status: 'connected', capabilities: [] } };
      const data: Partial<ChannelIntegration> = { name: 'n2' };
      api.update('ci-1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/channel-integrations/ci-1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== remove ==========
    it('remove_calls_delete_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.remove('ci-1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/channel-integrations/ci-1');
    });

    // ========== testConnection ==========
    it('testConnection_calls_post_with_test_suffix', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { ok: true, latencyMs: 120 } };
      api.testConnection('ci-1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/channel-integrations/ci-1/test');
    });
  });
}

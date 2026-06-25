// SessionSyncApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 SessionSyncApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  PageResult,
  SessionSync,
} from '../../../../main/ets/libs/types';
import { SessionSyncApi } from '../../../../main/ets/libs/api/modules/SessionSyncApi';

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

export default function sessionSyncApiTest() {
  describe('SessionSyncApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: SessionSyncApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new SessionSyncApi(client);
    });

    // ========== list ==========
    it('list_calls_get_with_agentId_and_paging', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.list('agent-1', { page: 1, size: 10 });
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/session-syncs')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
      expect(backend.requests[0].url.includes('page=1')).assertTrue();
      expect(backend.requests[0].url.includes('size=10')).assertTrue();
    });

    // ========== get ==========
    it('get_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ss-1', sessionId: 's1', sourceChannel: 'feishu', targetChannel: 'dingtalk', lastSyncedAt: '', messageCount: 0, status: 'synced' } };
      api.get('ss-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/session-syncs/ss-1');
    });

    // ========== create ==========
    it('create_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ss-1', sessionId: 's1', sourceChannel: 'feishu', targetChannel: 'dingtalk', lastSyncedAt: '', messageCount: 0, status: 'synced' } };
      const data: Partial<SessionSync> = { sessionId: 's1', sourceChannel: 'feishu', targetChannel: 'dingtalk' };
      api.create(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/session-syncs');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== update ==========
    it('update_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ss-1', sessionId: 's1', sourceChannel: 'feishu', targetChannel: 'dingtalk', lastSyncedAt: '', messageCount: 5, status: 'synced' } };
      const data: Partial<SessionSync> = { messageCount: 5 };
      api.update('ss-1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/session-syncs/ss-1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== remove ==========
    it('remove_calls_delete_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.remove('ss-1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/session-syncs/ss-1');
    });

    // ========== trigger ==========
    it('trigger_calls_post_with_trigger_suffix', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { ok: true, syncedAt: '2026-06-25T00:00:00Z' } };
      api.trigger('ss-1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/session-syncs/ss-1/trigger');
    });
  });
}

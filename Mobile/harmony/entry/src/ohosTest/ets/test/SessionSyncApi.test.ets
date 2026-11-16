// SessionSyncApi 单元测试 - 真实契约版（M9.2 同步域迁移）
// 后端事实源：session_sync.py @ /v1/sync（旧 /session-syncs 端点不存在，已退役）。
// 无 PUT 更新、无手动 trigger 端点——对应方法必须 throw 点名且不发任何网络请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
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

    it('list_gets_sync_sessions_with_agent_filter', 0, () => {
      api.list('a1', undefined);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/sync/sessions')).assertTrue();
      expect(url.includes('agent_id=a1')).assertTrue();
    });

    it('list_without_agent_gets_bare_path', 0, () => {
      api.list(undefined, undefined);
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/sessions');
    });

    it('get_gets_session_by_id', 0, () => {
      api.get('s1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/sessions/s1');
    });

    it('create_posts_session_create_contract', 0, () => {
      const metadata: Record<string, Object> = {};
      const body = { agent_id: 'a1', external_id: 'ext-1', metadata: metadata };
      api.create(body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/sessions');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('remove_deletes_session_by_id', 0, () => {
      api.remove('s1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/sessions/s1');
    });

    it('getHistory_carries_limit', 0, () => {
      api.getHistory('s1', 50);
      const url = backend.requests[0].url;
      expect(url.includes('/sync/sessions/s1/history')).assertTrue();
      expect(url.includes('limit=50')).assertTrue();
    });

    it('sendMessage_posts_message_contract', 0, () => {
      const metadata: Record<string, Object> = {};
      const body = { content: 'hello', channel_type: 'api', metadata: metadata };
      api.sendMessage('s1', body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/sessions/s1/messages');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('statistics_and_connections_hit_sync_paths', 0, () => {
      api.statistics();
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sync/statistics');
      api.connections();
      expect(backend.requests[1].url).assertEqual('https://api.example.com/sync/connections');
    });

    it('retiredUpdateTrigger_fire_no_request', 0, () => {
      api.update('s1', {});
      api.trigger('s1');
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

// AgentChannelsApi 单元测试 - TDD 垂直切片
// 验证 AgentChannelsApi 7 个方法的调用契约（嵌套资源路径）
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse, ChannelInfo, ChannelType, ChannelStatus } from '../../../../main/ets/libs/types';
import { AgentChannelsApi } from '../../../../main/ets/libs/api/modules/AgentChannelsApi';

class MockBackend implements HttpBackend {
  public requests: { method: string; url: string; body: Object | null }[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };

  async request(
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    this.requests.push({ method, url, body });
    return { status: 200, data: this.response };
  }
}

const makeChannel = (): ChannelInfo => ({
  id: 'c1', agentId: 'a1', type: 'feishu' as ChannelType, name: '飞书渠道',
  status: 'connected' as ChannelStatus, config: {}, enabled: true,
  createdAt: '', updatedAt: '',
});

export default function agentChannelsApiTest() {
  describe('AgentChannelsApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: AgentChannelsApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new AgentChannelsApi(client);
    });

    // ========== list ==========
    it('list_gets_agent_channels_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.list('a1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels');
    });

    it('list_returns_channel_array', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [makeChannel()] };
      let resolved: ApiResponse<ChannelInfo[]> | null = null;
      api.list('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data[0].id).assertEqual('c1');
      }, 10);
    });

    // ========== get ==========
    it('get_gets_channel_by_agent_and_channel_id', 0, () => {
      api.get('a1', 'c1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels/c1');
    });

    // ========== create ==========
    it('create_posts_to_agent_channels', 0, () => {
      const data: Partial<ChannelInfo> = { type: 'feishu' as ChannelType, name: 'n' };
      api.create('a1', data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== update ==========
    it('update_puts_to_channel_url', 0, () => {
      const data: Partial<ChannelInfo> = { name: 'updated' };
      api.update('a1', 'c1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels/c1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== remove ==========
    it('remove_deletes_channel', 0, () => {
      api.remove('a1', 'c1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels/c1');
    });

    // ========== testConnection ==========
    it('testConnection_posts_to_test_endpoint', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { success: true, message: 'ok' } };
      api.testConnection('a1', 'c1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels/c1/test');
    });

    it('testConnection_returns_result_object', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { success: true, message: 'ok' } };
      let resolved: ApiResponse<{ success: boolean; message: string }> | null = null;
      api.testConnection('a1', 'c1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.success).assertTrue();
        expect(resolved!.data.message).assertEqual('ok');
      }, 10);
    });

    // ========== toggle ==========
    it('toggle_puts_enabled_to_toggle_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: makeChannel() };
      api.toggle('a1', 'c1', true);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/agents/a1/channels/c1/toggle');
      expect(backend.requests[0].body).assertEqual({ enabled: true });
    });
  });
}

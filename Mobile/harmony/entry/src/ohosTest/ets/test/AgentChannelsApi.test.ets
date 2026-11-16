// AgentChannelsApi 单元测试 - 真实契约版（M9.2 渠道域迁移）
// 后端事实源：/v1/agents/{id}/channels 嵌套资源不存在；Agent 名下渠道的真实管理面是
// /v1/channel-configs?agent_id=（agent 隔离多实例）。
// 旧嵌套形态的 get/update/toggle 必须 throw 点名且不发任何网络请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
import { AgentChannelsApi, emptyExtra } from '../../../../main/ets/libs/api/modules/AgentChannelsApi';

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

    it('list_gets_channel_configs_scoped_to_agent', 0, () => {
      api.list('a1');
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/channel-configs')).assertTrue();
      expect(url.includes('agent_id=a1')).assertTrue();
    });

    it('create_posts_upsert_contract_scoped_to_agent', 0, () => {
      const body = {
        channel_type: 'feishu', enabled: true, app_id: 'cli-x', app_secret: 's',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      };
      api.create('a1', body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs?agent_id=a1');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('remove_deletes_by_channel_type_scoped_to_agent', 0, () => {
      api.remove('a1', 'feishu');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs/feishu?agent_id=a1');
    });

    it('testConnection_posts_to_channel_test_scoped_to_agent', 0, () => {
      api.testConnection('a1', 'feishu');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs/feishu/test?agent_id=a1');
    });

    it('retiredNestedEndpoints_fire_no_request', 0, () => {
      api.get('a1', 'c1');
      api.update('a1', 'c1', {});
      api.toggle('a1', 'c1', false);
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

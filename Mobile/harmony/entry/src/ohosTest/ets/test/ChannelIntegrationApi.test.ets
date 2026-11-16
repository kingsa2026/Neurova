// ChannelIntegrationApi 单元测试 - 真实契约版（M9.2 渠道域迁移）
// 后端事实源：/v1/channel-configs（自述前缀）+ /v1/channel-adapters + /v1/channel-sharing。
// 旧 /channel-integrations 端点不存在：对应方法必须 throw 点名且不发任何网络请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { ChannelIntegrationApi, ChannelConfigUpsertBody, emptyExtra } from '../../../main/ets/libs/api/modules/ChannelIntegrationApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  /** 响应体（可为信封/裸数组/裸 dict——模拟后端真实形状） */
  public responseBody: Object = new Object();

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.responseBody as Object as ApiResponse<Object> };
    return resp;
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

    it('list_gets_channel_configs_with_agent_query', 0, () => {
      api.list('default', undefined);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/channel-configs')).assertTrue();
      expect(url.includes('agent_id=default')).assertTrue();
    });

    it('getConfig_gets_by_channel_type_with_agent', 0, () => {
      api.getConfig('default', 'feishu');
      const url = backend.requests[0].url;
      expect(url.includes('/channel-configs/feishu')).assertTrue();
      expect(url.includes('agent_id=default')).assertTrue();
    });

    it('saveConfig_posts_upsert_contract_with_agent_query', 0, () => {
      const body: ChannelConfigUpsertBody = {
        channel_type: 'feishu', enabled: true, app_id: 'cli-x', app_secret: 's',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      };
      api.saveConfig('default', body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs?agent_id=default');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('removeConfig_deletes_by_channel_type_with_agent_query', 0, () => {
      api.removeConfig('default', 'feishu');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs/feishu?agent_id=default');
    });

    it('testConfig_posts_to_channel_test_with_agent_query', 0, () => {
      const body: ChannelConfigUpsertBody = {
        channel_type: 'feishu', enabled: true, app_id: '', app_secret: '',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      };
      api.testConfig('default', 'feishu', body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs/feishu/test?agent_id=default');
    });

    it('listAdapters_gets_adapter_health_view', 0, () => {
      api.listAdapters();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-adapters');
    });

    it('sharingStatus_gets_channel_sharing_status', 0, () => {
      api.sharingStatus();
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-sharing/status');
    });

    it('retiredIntegrationEndpoints_fire_no_request', 0, () => {
      api.get('ci-1');
      api.create(new Object());
      api.update('ci-1', new Object());
      api.remove('ci-1');
      api.testConnection('ci-1');
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

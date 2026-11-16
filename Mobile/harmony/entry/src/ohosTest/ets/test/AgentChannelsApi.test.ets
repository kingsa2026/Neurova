// AgentChannelsApi 单元测试 - 真实契约版（M9.2 渠道域迁移 + S4 P1-28/29 信封归一）
// 后端事实源：/v1/agents/{id}/channels 嵌套资源不存在；Agent 名下渠道的真实管理面是
// /v1/channel-configs?agent_id=（agent 隔离多实例）。
// 旧嵌套形态的 get/update/toggle 必须 throw 点名且不发任何网络请求。
// P1-28/29：后端 /v1/channel-configs 返回裸数组/裸 {success} dict——模块边界归一为 {code,data}。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { AgentChannelsApi, ChannelConfigUpsertBody, emptyExtra } from '../../../main/ets/libs/api/modules/AgentChannelsApi';
import { ChannelConfigDto } from '../../../main/ets/libs/api/modules/ChannelIntegrationApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 构造空 Record（ArkTS 禁非空字面量直接落 Record，集中此处） */
function emptyRecord(): Record<string, Object> {
  const r: Record<string, Object> = {};
  return r;
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

/** 构造一条渠道配置 DTO（裸数组元素形状，channel_config.py ChannelConfigResponse） */
function sampleConfig(): ChannelConfigDto {
  const dto: ChannelConfigDto = {
    channel_type: 'feishu',
    agent_id: 'a1',
    enabled: true,
    app_id_masked: 'cli-x***',
    use_stream: true,
    connected: false,
    extra: emptyRecord(),
  };
  return dto;
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

    it('list_normalizes_bare_array_body', 0, async () => {
      // 后端裸数组直返（无 {code,data} 信封）——模块边界必须归一，不得静默空
      const bare: ChannelConfigDto[] = [sampleConfig()];
      backend.responseBody = bare;
      const res = await api.list('a1');
      expect(res.code).assertEqual(0);
      expect(res.data!.length).assertEqual(1);
      expect(res.data![0].channel_type).assertEqual('feishu');
    });

    it('create_posts_upsert_contract_scoped_to_agent', 0, () => {
      const body: ChannelConfigUpsertBody = {
        channel_type: 'feishu', enabled: true, app_id: 'cli-x', app_secret: 's',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      };
      api.create('a1', body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/channel-configs?agent_id=a1');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('create_normalizes_success_dict_body', 0, async () => {
      // 后端写操作返回裸 {success,...} dict——归一后 code=0、data.success 可读
      const dict: Record<string, Object> = {
        'success': true, 'channel_type': 'feishu', 'agent_id': 'a1',
        'message': 'saved', 'needs_scan': false,
      };
      backend.responseBody = dict;
      const body: ChannelConfigUpsertBody = {
        channel_type: 'feishu', enabled: true, app_id: 'x', app_secret: '',
        use_stream: true, webhook_url: '', webhook_token: '', encrypt_key: '',
        verification_token: '', extra: emptyExtra(),
      };
      const res = await api.create('a1', body);
      expect(res.code).assertEqual(0);
      expect(String((res.data as Record<string, Object>)['success'])).assertEqual('true');
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

    it('testConnection_reads_bare_result_object', 0, async () => {
      // ChannelTestResult 裸对象——归一后 success/message 从 data 读取，不再恒 false
      const dict: Record<string, Object> = { 'success': true, 'message': 'ok', 'needs_scan': false };
      backend.responseBody = dict;
      const res = await api.testConnection('a1', 'feishu');
      expect(res.code).assertEqual(0);
      expect(res.data!.success).assertEqual(true);
      expect(res.data!.message).assertEqual('ok');
    });

    it('retiredNestedEndpoints_fire_no_request', 0, () => {
      api.get('a1', 'c1');
      api.update('a1', 'c1', new Object());
      api.toggle('a1', 'c1', false);
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

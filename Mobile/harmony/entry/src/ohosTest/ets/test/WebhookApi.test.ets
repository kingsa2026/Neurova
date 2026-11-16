// WebhookApi 单元测试 - P1-34 新增模块（对齐 /v1/webhooks 真实契约）
// 后端 webhooks.py：GET/POST /v1/webhooks（裸数组/裸对象）、POST /{id}/test（投递记录）、
// GET /{id}/deliveries（裸数组）。模块边界归一为 {code,data}。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { WebhookApi, WebhookUpsertBody } from '../../../main/ets/libs/api/modules/WebhookApi';

/** MockBackend 录制的请求 */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
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

/** WebhookInfo 裸对象（webhooks.py 形状） */
function sampleWebhookDict(): Record<string, Object> {
  const events: string[] = ['message.received', 'task.completed'];
  const dict: Record<string, Object> = {
    'webhook_id': 'wh_1',
    'name': '消息推送',
    'url': 'https://example.com/hook',
    'events': events,
    'enabled': true,
    'user_id': 'u1',
    'created_at': 1700000000,
    'updated_at': 1700000100,
  };
  return dict;
}

/** 第二条 WebhookInfo（禁用态，供聚合用例区分计数） */
function sampleWebhookDict2(): Record<string, Object> {
  const events: string[] = ['agent.created'];
  const dict: Record<string, Object> = {
    'webhook_id': 'wh_2',
    'name': '智能体通知',
    'url': 'https://example.com/hook2',
    'events': events,
    'enabled': false,
    'user_id': 'u1',
    'created_at': 1700000000,
    'updated_at': 1700000100,
  };
  return dict;
}

export default function webhookApiTest() {
  describe('WebhookApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: WebhookApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new WebhookApi(client);
    });

    it('list_gets_webhooks_and_normalizes_bare_array', 0, async () => {
      const arr: Record<string, Object>[] = [sampleWebhookDict()];
      backend.responseBody = arr;
      const res = await api.list();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/webhooks');
      expect(res.code).assertEqual(0);
      expect(res.data!.length).assertEqual(1);
      expect(res.data![0].id).assertEqual('wh_1');
      expect(res.data![0].status).assertEqual('active');
      expect(res.data![0].events.length).assertEqual(2);
    });

    it('list_aggregates_deliveries_into_counts', 0, async () => {
      // GET /webhooks 后模块会按 webhook 逐个 GET /deliveries——顺序桩依次给响应：
      // wh_1 有一条 delivered、wh_2 有一条 failed，各自聚合出真实计数。
      const hooks: Record<string, Object>[] = [sampleWebhookDict(), sampleWebhookDict2()];
      const deliveries1: Record<string, Object> = {
        'delivery_id': 'd1', 'webhook_id': 'wh_1', 'event_type': 'test',
        'status': 'delivered', 'response_code': 200, 'attempts': 1, 'created_at': 1700000200,
      };
      const deliveries2: Record<string, Object> = {
        'delivery_id': 'd2', 'webhook_id': 'wh_2', 'event_type': 'test',
        'status': 'failed', 'response_code': 500, 'attempts': 1, 'created_at': 1700000300,
      };
      const responses: Object[] = [hooks, [deliveries1], [deliveries2]];
      const seqBackend = new SequentialBackend(responses);
      const seqClient = HttpClient.getInstanceWithBackend(seqBackend);
      seqClient.setBaseUrl('https://api.example.com');
      const seqApi = new WebhookApi(seqClient);
      const res = await seqApi.list();
      expect(res.code).assertEqual(0);
      expect(res.data!.length).assertEqual(2);
      expect(res.data![0].successCount).assertEqual(1);
      expect(res.data![0].failureCount).assertEqual(0);
      expect(res.data![1].failureCount).assertEqual(1);
      expect(res.data![1].lastTriggeredAt!.length > 0).assertTrue();
    });

    it('create_posts_contract_and_maps_bare_object', 0, async () => {
      backend.responseBody = sampleWebhookDict();
      const body: WebhookUpsertBody = {
        name: '新钩子', url: 'https://example.com/new', events: ['message.received'], secret: 's3cret',
      };
      const res = await api.create(body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/webhooks');
      expect(res.code).assertEqual(0);
      expect(res.data!.name).assertEqual('消息推送');
    });

    it('testTrigger_maps_delivery_status', 0, async () => {
      const delivery: Record<string, Object> = {
        'delivery_id': 'd9', 'webhook_id': 'wh_1', 'event_type': 'test',
        'status': 'delivered', 'response_code': 200, 'attempts': 1, 'created_at': 1700000400,
      };
      backend.responseBody = delivery;
      const res = await api.testTrigger('wh_1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/webhooks/wh_1/test');
      expect(res.code).assertEqual(0);
    });

    it('remove_deletes_webhook', 0, () => {
      const dict: Record<string, Object> = { 'code': 0, 'message': 'Webhook deleted' };
      backend.responseBody = dict;
      api.remove('wh_1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/webhooks/wh_1');
    });
  });
}

/** 顺序响应后端：按调用次序依次返回预设响应体（list 聚合投递记录用） */
class SequentialBackend implements HttpBackend {
  private responses: Object[];
  public requests: string[] = [];

  constructor(responses: Object[]) {
    this.responses = responses;
  }

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    this.requests.push(url);
    const idx = this.requests.length - 1 < this.responses.length
      ? this.requests.length - 1 : this.responses.length - 1;
    const resp: HttpBackendResponse = {
      status: 200,
      data: this.responses[idx] as Object as ApiResponse<Object>,
    };
    return resp;
  }
}

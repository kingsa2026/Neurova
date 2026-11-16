// MonitorApi 单元测试 - 真实契约版（M9.2 监控域迁移）
// 后端事实源：/v1/monitor（status/resources/connections/alerts，admin 门控）、
// /v1/neuron、/v1/notifications、/v1/files。
// 旧 /monitor/stats|metrics|logs|neurons 与 fire 端点后端不存在：
// 对应方法必须 throw 点名，且**不发任何网络请求**（本文件钉住这一行为）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { MonitorApi } from '../../../main/ets/libs/api/modules/MonitorApi';

/** MockBackend 录制的请求（显式接口，替代内联对象字面量类型） */
interface RecordedRequest {
  method: string;
  url: string;
  body: Object | null;
}

/** 构造空 Record（ArkTS 对象字面量须对应显式类型，集中此处） */
function emptyRecord(): Record<string, Object> {
  const r: Record<string, Object> = {};
  return r;
}

/** 构造 ApiResponse 信封（data 须传显式类型值，禁内联对象字面量） */
function apiResponse(data: Object): ApiResponse<Object> {
  const resp: ApiResponse<Object> = { code: 0, message: 'ok', data: data };
  return resp;
}

// Mock 后端实现（参考 MemoryApi.test.ets 模式）
class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public response: ApiResponse<Object> = apiResponse(emptyRecord());

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

export default function monitorApiTest() {
  describe('MonitorApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: MonitorApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new MonitorApi(client);
    });

    // ========== 监控真实面（/monitor/*）==========

    it('getSystemStatus_calls_get_monitor_status', 0, () => {
      api.getSystemStatus();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/monitor/status');
    });

    it('getResources_calls_get_monitor_resources', 0, () => {
      api.getResources();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/monitor/resources');
    });

    it('listConnections_calls_get_monitor_connections', 0, () => {
      api.listConnections();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/monitor/connections');
    });

    it('listAlerts_carries_level_resolved_limit_query', 0, () => {
      api.listAlerts('warning', false, 50);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/monitor/alerts')).assertTrue();
      expect(url.includes('level=warning')).assertTrue();
      expect(url.includes('resolved=false')).assertTrue();
      expect(url.includes('limit=50')).assertTrue();
    });

    it('resolveAlert_posts_to_alert_resolve', 0, () => {
      api.resolveAlert('a1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/monitor/alerts/a1/resolve');
    });

    // ========== NEURON（/neuron/*）==========

    it('listNeurons_gets_neuron_entities_with_type_filter', 0, () => {
      api.listNeurons('service', { page: 1, size: 200 });
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/api/neuron/entities')).assertTrue();
      expect(url.includes('entity_type=service')).assertTrue();
      expect(url.includes('limit=200')).assertTrue();
    });

    it('createNeuronEntity_posts_name_type_metadata', 0, () => {
      const metadata: Record<string, Object> = {};
      api.createNeuronEntity('网关', 'service', metadata);
      expect(backend.requests[0].method).assertEqual('POST');
      // neuron 自述前缀挂 /api 下（无 /v1）——真实挂载点为 /api/neuron/*
      expect(backend.requests[0].url).assertEqual('https://api.example.com/api/neuron/entities');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['name']).assertEqual('网关');
      expect(body['entity_type']).assertEqual('service');
    });

    it('getNeuronStats_gets_neuron_stats', 0, () => {
      api.getNeuronStats();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/api/neuron/stats');
    });

    // ========== 通知 / 文件（真实端点）==========

    it('listNotifications_unread_only_maps_to_read_false', 0, () => {
      api.listNotifications(true);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/notifications')).assertTrue();
      expect(url.includes('read=false')).assertTrue();
    });

    it('markAllNotificationsRead_posts_mark_all_read', 0, () => {
      api.markAllNotificationsRead();
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/notifications/mark-all-read');
    });

    it('listFiles_gets_bare_array_from_files', 0, () => {
      api.listFiles(undefined, undefined);
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/files');
    });

    // ========== 退役端点 vs 已接线端点（P1-35）==========

    it('wired_stats_logs_clearlogs_fire_real_requests', 0, async () => {
      // 已接线：stats/logs/clearLogs 走真实端点，各发一条请求
      // （mock 响应非对应形状时模块会抛错，但不影响「发了请求」的断言）
      try { await api.listStats('day'); } catch (e) { }
      try { await api.listLogs(undefined, undefined, undefined); } catch (e) { }
      try { await api.clearLogs(); } catch (e) { }
      expect(backend.requests.length).assertEqual(3);
      expect(backend.requests[0].url).assertEqual('https://api.example.com/stats');
      expect(backend.requests[1].url).assertEqual('https://api.example.com/logs');
      expect(backend.requests[2].method).assertEqual('DELETE');
    });

    it('retired_endpoints_throw_without_request', 0, async () => {
      const before: number = backend.requests.length;
      let threw = 0;
      try { await api.getStat('k'); } catch (e) { threw += 1; }
      try { await api.listMetrics(undefined, undefined); } catch (e) { threw += 1; }
      try { await api.pushMetric({ name: 'x', value: 1, unit: '', timestamp: '' }); } catch (e) { threw += 1; }
      try { await api.getLog('l1'); } catch (e) { threw += 1; }
      try { await api.removeLog('l1'); } catch (e) { threw += 1; }
      try { await api.getNeuron('n1'); } catch (e) { threw += 1; }
      try { await api.updateNeuron('n1', {}); } catch (e) { threw += 1; }
      try { await api.fireNeuron('n1'); } catch (e) { threw += 1; }
      try { await api.getNotification('n1'); } catch (e) { threw += 1; }
      expect(threw).assertEqual(9);
      expect(backend.requests.length).assertEqual(before);
    });
  });
}

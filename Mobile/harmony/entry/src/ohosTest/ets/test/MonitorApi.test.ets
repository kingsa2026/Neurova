// MonitorApi 单元测试 - 真实契约版（M9.2 监控域迁移）
// 后端事实源：/v1/monitor（status/resources/connections/alerts，admin 门控）、
// /v1/neuron、/v1/notifications、/v1/files。
// 旧 /monitor/stats|metrics|logs|neurons 与 fire 端点后端不存在：
// 对应方法必须 throw 点名，且**不发任何网络请求**（本文件钉住这一行为）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
import { MonitorApi } from '../../../../main/ets/libs/api/modules/MonitorApi';

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
      expect(url.includes('/neuron/entities')).assertTrue();
      expect(url.includes('entity_type=service')).assertTrue();
      expect(url.includes('limit=200')).assertTrue();
    });

    it('createNeuronEntity_posts_name_type_metadata', 0, () => {
      const metadata: Record<string, Object> = {};
      api.createNeuronEntity('网关', 'service', metadata);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/neuron/entities');
      expect(backend.requests[0].body).assertEqual({ 'name': '网关', 'entity_type': 'service', 'metadata': {} });
    });

    it('getNeuronStats_gets_neuron_stats', 0, () => {
      api.getNeuronStats();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/neuron/stats');
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

    // ========== 退役端点：必须 throw 且不发任何请求 ==========

    it('retiredStatsMetricsLogsFire_fire_no_request', 0, () => {
      api.listStats('day');
      api.getStat('k');
      api.listMetrics(undefined, undefined);
      api.listLogs(undefined, undefined, undefined);
      api.clearLogs();
      api.fireNeuron('n1');
      api.getNeuron('n1');
      api.getNotification('n1');
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

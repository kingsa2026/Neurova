// MonitorApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 MonitorApi 调用契约（method/url/body/返回值）
// 覆盖 6 个实体核心方法：Stat、MonitorMetric、LogEntry、NotificationItem、FileItem、Neuron
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  Stat,
  MonitorMetric,
  LogEntry,
  LogLevel,
  NotificationItem,
  FileItem,
  Neuron,
  NeuronState,
  PageResult,
  PageParams,
} from '../../../../main/ets/libs/types';
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

    // ========== Stat 实体（2 测试）==========
    it('listStats_calls_get_with_period_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listStats('day');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/stats?period=day');
    });

    it('getStat_calls_get_with_key_in_url', 0, () => {
      api.getStat('active_users');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/stats/active_users');
    });

    // ========== MonitorMetric 实体（2 测试）==========
    it('listMetrics_calls_get_with_name_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listMetrics('cpu_usage');
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('name=cpu_usage')).assertTrue();
    });

    it('pushMetric_posts_body_to_metrics', 0, () => {
      const data: Partial<MonitorMetric> = { name: 'cpu_usage', value: 0.45, unit: 'ratio', timestamp: '2026-06-25T00:00:00Z' };
      api.pushMetric(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/metrics');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== LogEntry 实体（3 测试）==========
    it('listLogs_passes_level_and_source_filters', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listLogs({ page: 1, size: 20 }, 'error' as LogLevel, 'HttpClient');
      const url = backend.requests[0].url;
      expect(url.includes('level=error')).assertTrue();
      expect(url.includes('source=HttpClient')).assertTrue();
    });

    it('clearLogs_posts_before_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.clearLogs('2026-06-01T00:00:00Z');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/logs/clear');
      expect(backend.requests[0].body).assertEqual({ before: '2026-06-01T00:00:00Z' });
    });

    it('removeLog_deletes_by_id', 0, () => {
      api.removeLog('l1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/logs/l1');
    });

    // ========== NotificationItem 实体（3 测试）==========
    it('listNotifications_passes_unreadOnly_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listNotifications(true);
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/notifications?unreadOnly=true');
    });

    it('markNotificationRead_posts_to_read_endpoint', 0, () => {
      api.markNotificationRead('n1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/notifications/n1/read');
    });

    it('markAllNotificationsRead_posts_to_read_all', 0, () => {
      api.markAllNotificationsRead();
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/notifications/read-all');
    });

    // ========== FileItem 实体（2 测试）==========
    it('listFiles_filters_by_parentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listFiles('root');
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('parentId=root')).assertTrue();
    });

    it('createFolder_posts_to_folder_endpoint', 0, () => {
      const data: Partial<FileItem> = { name: 'docs', type: 'folder', path: '/docs', size: 0, modifiedAt: '' };
      api.createFolder(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/files/folder');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Neuron 实体（2 测试）==========
    it('listNeurons_filters_by_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listNeurons('a1');
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('agentId=a1')).assertTrue();
    });

    it('fireNeuron_posts_to_fire_endpoint', 0, () => {
      api.fireNeuron('n1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/monitor/neurons/n1/fire');
    });
  });
}

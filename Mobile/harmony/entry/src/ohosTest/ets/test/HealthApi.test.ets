// HealthApi 单元测试 - TDD 垂直切片
// 验证 HealthApi 3 个方法的调用契约
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse, SystemHealth, ServiceHealth } from '../../../../main/ets/libs/types';
import { HealthApi } from '../../../../main/ets/libs/api/modules/HealthApi';

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

export default function healthApiTest() {
  describe('HealthApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: HealthApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new HealthApi(client);
    });

    // ========== check ==========
    it('check_gets_health_endpoint', 0, () => {
      backend.response = {
        code: 0, message: 'ok',
        data: { status: 'healthy', score: 100, services: [], checkedAt: '2026-01-01' },
      };
      api.check();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/health');
    });

    it('check_returns_system_health', 0, () => {
      const health: SystemHealth = {
        status: 'healthy', score: 100, services: [], checkedAt: '2026-01-01',
      };
      backend.response = { code: 0, message: 'ok', data: health };
      let resolved: ApiResponse<SystemHealth> | null = null;
      api.check().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.status).assertEqual('healthy');
        expect(resolved!.data.score).assertEqual(100);
      }, 10);
    });

    // ========== getService ==========
    it('getService_gets_service_by_name', 0, () => {
      backend.response = {
        code: 0, message: 'ok',
        data: { name: 'db', status: 'healthy', latency: 5 },
      };
      api.getService('db');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/health/services/db');
    });

    it('getService_returns_service_health', 0, () => {
      const svc: ServiceHealth = { name: 'redis', status: 'healthy', latency: 2 };
      backend.response = { code: 0, message: 'ok', data: svc };
      let resolved: ApiResponse<ServiceHealth> | null = null;
      api.getService('redis').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.name).assertEqual('redis');
        expect(resolved!.data.latency).assertEqual(2);
      }, 10);
    });

    // ========== getMetrics ==========
    it('getMetrics_gets_metrics_endpoint', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { cpu: 0.5, mem: 0.3 } };
      api.getMetrics();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/health/metrics');
    });

    it('getMetrics_returns_record', 0, () => {
      const metrics: Record<string, number> = { cpu: 0.4, mem: 0.6 };
      backend.response = { code: 0, message: 'ok', data: metrics };
      let resolved: ApiResponse<Record<string, number>> | null = null;
      api.getMetrics().then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.data.cpu).assertEqual(0.4);
      }, 10);
    });
  });
}

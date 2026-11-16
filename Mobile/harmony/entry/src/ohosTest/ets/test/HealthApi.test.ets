// HealthApi 单元测试 - 真实契约版（P1-30 端点核对 + P1-28/29 信封归一）
// 后端事实源：health.py @ /v1/health，全部裸形状，模块边界归一：
//   check() = GET /health（总览）+ GET /health/checks（各项）→ 映射为 FE SystemHealth；
//   getService(name) = GET /health/checks/{name} → 映射为 ServiceHealth（duration→latency）；
//   旧 /health/services/*、/health/metrics 后端不存在：getMetrics 诚实 throw 且不发任何请求。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { HealthApi } from '../../../main/ets/libs/api/modules/HealthApi';

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
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const resp: HttpBackendResponse = { status: 200, data: this.responseBody as Object as ApiResponse<Object> };
    return resp;
  }
}

/** 顺序响应后端：check() 先打 /health 再打 /health/checks，按调用次序给响应体 */
class SequentialBackend implements HttpBackend {
  private responses: Object[];
  public requests: RecordedRequest[] = [];

  constructor(responses: Object[]) {
    this.responses = responses;
  }

  async request(
    method: string, url: string, body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    const idx = this.requests.length - 1 < this.responses.length
      ? this.requests.length - 1 : this.responses.length - 1;
    const resp: HttpBackendResponse = { status: 200, data: this.responses[idx] as Object as ApiResponse<Object> };
    return resp;
  }
}

/** HealthStatusResponse 裸 dict（health.py 形状；timestamp=2026-01-01T00:00:00Z） */
function statusDict(): Record<string, Object> {
  const dict: Record<string, Object> = {
    'status': 'healthy', 'timestamp': 1767225600, 'uptime': 3600,
    'checks_count': 2, 'healthy_count': 2, 'unhealthy_count': 0, 'message': 'ok',
  };
  return dict;
}

/** CheckResultResponse 裸 dict（health.py 形状） */
function checkDict(name: string, duration: number): Record<string, Object> {
  const dict: Record<string, Object> = {
    'name': name, 'status': 'healthy', 'message': 'ok', 'duration': duration, 'check_type': 'liveness',
  };
  return dict;
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
    it('check_gets_health_endpoint', 0, async () => {
      const responses: Object[] = [statusDict(), []];
      const seqBackend = new SequentialBackend(responses);
      const seqClient = HttpClient.getInstanceWithBackend(seqBackend);
      seqClient.setBaseUrl('https://api.example.com');
      const seqApi = new HealthApi(seqClient);
      await seqApi.check();
      expect(seqBackend.requests[0].method).assertEqual('GET');
      expect(seqBackend.requests[0].url).assertEqual('https://api.example.com/health');
      expect(seqBackend.requests[1].url).assertEqual('https://api.example.com/health/checks');
    });

    it('check_returns_system_health', 0, async () => {
      // 后端裸形状（总览 dict + 检查项裸数组）——边界归一后映射为 SystemHealth（score=健康项占比）
      const checks: Record<string, Object>[] = [checkDict('db', 5), checkDict('redis', 2)];
      const responses: Object[] = [statusDict(), checks];
      const seqBackend = new SequentialBackend(responses);
      const seqClient = HttpClient.getInstanceWithBackend(seqBackend);
      seqClient.setBaseUrl('https://api.example.com');
      const seqApi = new HealthApi(seqClient);
      const res = await seqApi.check();
      expect(res.code).assertEqual(0);
      expect(res.data.status).assertEqual('healthy');
      expect(res.data.score).assertEqual(100);
      expect(res.data.services.length).assertEqual(2);
    });

    // ========== getService ==========
    it('getService_gets_service_by_name', 0, () => {
      backend.responseBody = checkDict('db', 5);
      api.getService('db');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/health/checks/db');
    });

    it('getService_returns_service_health', 0, async () => {
      // CheckResultResponse 裸对象——归一后映射为 ServiceHealth（duration→latency）
      backend.responseBody = checkDict('redis', 2);
      const res = await api.getService('redis');
      expect(res.code).assertEqual(0);
      expect(res.data.name).assertEqual('redis');
      expect(res.data.status).assertEqual('healthy');
      expect(res.data.latency).assertEqual(2);
    });

    // ========== getMetrics（后端无 /health/metrics：诚实 throw，不发任何请求）==========
    it('getMetrics_throws_and_fires_no_request', 0, async () => {
      let thrown = '';
      try {
        await api.getMetrics();
      } catch (e) {
        thrown = (e as Error).message;
      }
      expect(thrown.length > 0).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('getMetrics_error_names_real_resource_surface', 0, async () => {
      let thrown = '';
      try {
        await api.getMetrics();
      } catch (e) {
        thrown = (e as Error).message;
      }
      expect(thrown.includes('/v1/health/metrics')).assertTrue();
      expect(thrown.includes('stats/system')).assertTrue();
    });
  });
}

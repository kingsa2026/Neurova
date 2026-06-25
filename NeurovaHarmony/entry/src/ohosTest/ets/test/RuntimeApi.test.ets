// RuntimeApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 RuntimeApi 调用契约（method/url/body/返回值）
// 不真实发起网络请求，符合"不直接调用后端接口"规则
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  PageResult,
  ScheduleTask,
  ContextMessage,
  ComputerTask,
  TraceEntry,
  TrajectoryPoint,
  SleepStatus,
  FirewallRule,
} from '../../../../main/ets/libs/types';
import { RuntimeApi } from '../../../../main/ets/libs/api/modules/RuntimeApi';

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

export default function runtimeApiTest() {
  describe('RuntimeApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: RuntimeApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new RuntimeApi(client);
    });

    // ========== ScheduleTask: list/create ==========
    it('listScheduleTasks_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listScheduleTasks('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/scheduler')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('createScheduleTask_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 's1', agentId: 'a1', name: 'n', cron: '* * * * *', status: 'pending', createdAt: '' } };
      const data: Partial<ScheduleTask> = { agentId: 'a1', name: 'n', cron: '* * * * *' };
      api.createScheduleTask(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/scheduler');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== ContextMessage: list/remove ==========
    it('listContextMessages_calls_get_with_sessionId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listContextMessages('session-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/context')).assertTrue();
      expect(backend.requests[0].url.includes('sessionId=session-1')).assertTrue();
    });

    it('removeContextMessage_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeContextMessage('c1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/context/c1');
    });

    // ========== ComputerTask: list/create/remove ==========
    it('listComputerTasks_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listComputerTasks('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/computer')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('createComputerTask_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'ct1', agentId: 'a1', action: 'click', status: 'pending', startedAt: '' } };
      const data: Partial<ComputerTask> = { agentId: 'a1', action: 'click' };
      api.createComputerTask(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/computer');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('removeComputerTask_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeComputerTask('ct1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/computer/ct1');
    });

    // ========== TraceEntry: list/remove ==========
    it('listTraces_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listTraces('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/traces')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('removeTrace_calls_delete_with_id', 0, () => {
      backend.response = { code: 0, message: 'ok', data: {} };
      api.removeTrace('t1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/traces/t1');
    });

    // ========== TrajectoryPoint: list/get ==========
    it('listTrajectory_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listTrajectory('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/trajectory')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('getTrajectoryPoint_calls_get_with_id_in_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'tp1', agentId: 'a1', sessionId: 's1', step: 1, action: 'click', observation: 'o', timestamp: '' } };
      api.getTrajectoryPoint('tp1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/trajectory/tp1');
    });

    // ========== SleepStatus: get/setMode/awaken ==========
    it('getSleepStatus_calls_get_with_agentId_query', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', isSleeping: false, mode: 'idle', pendingTasks: 0 } };
      api.getSleepStatus('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/sleep')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('setSleepMode_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', isSleeping: true, mode: 'deep', pendingTasks: 0 } };
      api.setSleepMode('agent-1', 'deep');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/sleep');
      expect(backend.requests[0].body).assertEqual({ agentId: 'agent-1', mode: 'deep' });
    });

    it('awaken_calls_post_to_awaken_endpoint_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { agentId: 'a1', isSleeping: false, mode: 'idle', pendingTasks: 0 } };
      api.awaken('agent-1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/sleep/awaken');
      expect(backend.requests[0].body).assertEqual({ agentId: 'agent-1' });
    });

    // ========== FirewallRule: list/create/update ==========
    it('listFirewallRules_calls_get_with_agentId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listFirewallRules('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url.includes('/v1/runtime/firewall')).assertTrue();
      expect(backend.requests[0].url.includes('agentId=agent-1')).assertTrue();
    });

    it('createFirewallRule_calls_post_with_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'f1', agentId: 'a1', resource: '/path', action: 'allow', scope: 'outbound', enabled: true, createdAt: '' } };
      const data: Partial<FirewallRule> = { agentId: 'a1', resource: '/path', action: 'allow', scope: 'outbound', enabled: true };
      api.createFirewallRule(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/firewall');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('updateFirewallRule_calls_put_with_id_and_body', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { id: 'f1', agentId: 'a1', resource: '/path', action: 'deny', scope: 'outbound', enabled: true, createdAt: '' } };
      const data: Partial<FirewallRule> = { action: 'deny' };
      api.updateFirewallRule('f1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/runtime/firewall/f1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('getSleepStatus_returns_sleep_status_data', 0, () => {
      const status: SleepStatus = { agentId: 'a1', isSleeping: true, sleepSince: '', mode: 'deep', pendingTasks: 3 };
      backend.response = { code: 0, message: 'ok', data: status };
      let resolved: ApiResponse<SleepStatus> | null = null;
      api.getSleepStatus('a1').then(r => { resolved = r; });
      setTimeout(() => {
        expect(resolved!.code).assertEqual(0);
        expect(resolved!.data.isSleeping).assertTrue();
        expect(resolved!.data.mode).assertEqual('deep');
        expect(resolved!.data.pendingTasks).assertEqual(3);
      }, 10);
    });
  });
}

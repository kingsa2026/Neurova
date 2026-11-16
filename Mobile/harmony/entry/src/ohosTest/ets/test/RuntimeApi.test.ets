// RuntimeApi 单元测试 - 真实契约版
// 通过 HttpBackend 接口注入 mock，验证 RuntimeApi 调用契约（method/url/body/返回值）
// 端点词汇与后端挂载同源：/v1/scheduler、/v1/trace、/v1/sleep、/v1/firewall；
// 上下文消息/计算机任务/轨迹点后端无对应端点——断言不发请求且返回诚实空态/显式失败。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../main/ets/libs/types';
import { RuntimeApi } from '../../../main/ets/libs/api/modules/RuntimeApi';

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

// Mock 后端实现：按 method+url 返回不同响应（防火墙"先取列表再合并更新"需要）
class MockBackend implements HttpBackend {
  public requests: RecordedRequest[] = [];
  public response: ApiResponse<Object> = apiResponse(emptyRecord());
  public getResponse: ApiResponse<Object> | null = null;

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<HttpBackendResponse> {
    const recorded: RecordedRequest = { method: method, url: url, body: body };
    this.requests.push(recorded);
    if (method === 'GET' && this.getResponse !== null) {
      const got: HttpBackendResponse = { status: 200, data: this.getResponse };
      return got;
    }
    const resp: HttpBackendResponse = { status: 200, data: this.response };
    return resp;
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

    // ========== Scheduler：列表/创建/更新/触发/删除 ==========

    it('listScheduleTasks_calls_get_scheduler_tasks_with_agent_and_limit', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listScheduleTasks('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/scheduler/tasks')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('createScheduleTask_posts_taskcreate_contract', 0, () => {
      const taskData: Record<string, Object> = { 'task_id': 't1' };
      backend.response = apiResponse(taskData);
      api.createScheduleTask({
        agentId: 'agent-1',
        name: '日报',
        cron: '0 9 * * *',
        payload: { 'k': 'v' },
      });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/scheduler/tasks');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['name']).assertEqual('日报');
      expect(body['action']).assertEqual('custom');
      expect(body['cron_expression']).assertEqual('0 9 * * *');
    });

    it('updateScheduleTask_running_status_routes_to_run_endpoint', 0, () => {
      const taskData: Record<string, Object> = { 'task_id': 't1' };
      backend.response = apiResponse(taskData);
      api.updateScheduleTask('t1', { status: 'running' });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/scheduler/tasks/t1/run');
    });

    it('updateScheduleTask_cron_routes_to_put', 0, () => {
      const taskData: Record<string, Object> = { 'task_id': 't1' };
      backend.response = apiResponse(taskData);
      api.updateScheduleTask('t1', { cron: '0 10 * * *' });
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/scheduler/tasks/t1');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['cron_expression']).assertEqual('0 10 * * *');
    });

    it('removeScheduleTask_calls_delete', 0, () => {
      backend.response = apiResponse(emptyRecord());
      api.removeScheduleTask('t1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/scheduler/tasks/t1');
    });

    // ========== Trace：列表/删除（后端无 DELETE） ==========

    it('listTraces_calls_get_trace_with_agent_and_limit', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listTraces('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/trace')).assertTrue();
      expect(url.includes('agent_id=agent-1')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('removeTrace_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.removeTrace('tr1');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    // ========== 无真实数据源的端点：显式抛错点名，不发请求 ==========

    it('listContextMessages_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.listContextMessages('s1');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('listComputerTasks_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.listComputerTasks('agent-1');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('createComputerTask_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.createComputerTask({ agentId: 'agent-1', action: 'click' });
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    it('listTrajectory_throws_without_request', 0, () => {
      let threw = false;
      try {
        api.listTrajectory('agent-1');
      } catch (e) {
        threw = true;
      }
      expect(threw).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });

    // ========== Sleep：状态/设置/唤醒 ==========

    it('getSleepStatus_calls_get_sleep_status_path', 0, () => {
      const sleepData: Record<string, Object> = { 'agent_id': 'agent-1', 'is_sleeping': true, 'sleep_phase': 'deep', 'sleep_cycles': 2 };
      backend.response = apiResponse(sleepData);
      api.getSleepStatus('agent-1');
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sleep/agent-1/status');
    });

    it('setSleepMode_puts_sleep_settings_with_sleep_mode', 0, () => {
      const sleepData: Record<string, Object> = { 'agent_id': 'agent-1', 'is_sleeping': false, 'sleep_phase': 'awake', 'sleep_cycles': 0 };
      backend.response = apiResponse(sleepData);
      api.setSleepMode('agent-1', 'deep');
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sleep/agent-1/settings');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['sleep_mode']).assertEqual('deep');
    });

    it('awaken_posts_sleep_wake_path', 0, () => {
      backend.response = apiResponse(emptyRecord());
      api.awaken('agent-1');
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/sleep/agent-1/wake');
    });

    // ========== Firewall：列表/创建/启停/删除 ==========

    it('listFirewallRules_calls_get_firewall_rules', 0, () => {
      backend.response = { code: 0, message: 'ok', data: [] };
      api.listFirewallRules('agent-1', { page: 1, size: 20 });
      expect(backend.requests[0].method).assertEqual('GET');
      const url = backend.requests[0].url;
      expect(url.includes('/firewall/rules')).assertTrue();
      expect(url.includes('limit=100')).assertTrue();
    });

    it('createFirewallRule_posts_firewallrulecreate_contract', 0, () => {
      const ruleData: Record<string, Object> = { 'rule_id': 'r1' };
      backend.response = apiResponse(ruleData);
      api.createFirewallRule({ agentId: 'agent-1', resource: '1.2.3.4', action: 'deny', enabled: true });
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/firewall/rules');
      const body = backend.requests[0].body as Record<string, Object>;
      expect(body['value']).assertEqual('1.2.3.4');
      expect(body['action']).assertEqual('block');
      expect(body['rule_type']).assertEqual('ip');
    });

    it('updateFirewallRule_enabled_merges_existing_rule', 0, () => {
      const existingRule: Record<string, Object> = { 'rule_id': 'r1', 'name': '1.2.3.4', 'rule_type': 'ip', 'action': 'block', 'value': '1.2.3.4', 'enabled': true, 'created_at': 0, 'updated_at': 0 };
      const existingRules: Record<string, Object>[] = [existingRule];
      backend.getResponse = apiResponse(existingRules);
      const ruleData: Record<string, Object> = { 'rule_id': 'r1', 'enabled': false };
      backend.response = apiResponse(ruleData);
      api.updateFirewallRule('r1', { enabled: false });
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[1].method).assertEqual('PUT');
      expect(backend.requests[1].url).assertEqual('https://api.example.com/firewall/rules/r1');
      const body = backend.requests[1].body as Record<string, Object>;
      expect(body['enabled']).assertEqual(false);
      expect(body['value']).assertEqual('1.2.3.4');
    });

    it('removeFirewallRule_calls_delete', 0, () => {
      backend.response = apiResponse(emptyRecord());
      api.removeFirewallRule('r1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/firewall/rules/r1');
    });
  });
}

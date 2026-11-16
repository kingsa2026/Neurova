// CollaborationApi 单元测试 - 真实契约版（M9.2 协作域迁移 + P1-28/29 信封归一）
// 后端事实源：/v1/collaboration（templates/start/history/sessions/stats）+ /v1/tasks（看板任务）。
// P1-35 后 projects/teams/workflows 已接线到 /v1/projects、/v1/teams、/v1/neurflow/workflows；
// 任务删除后端无路由——退役面仅剩 removeTask，必须 throw 点名且**不发任何网络请求**。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend, HttpBackendResponse } from '../../../main/ets/libs/api/HttpClient';
import { ApiResponse, Task } from '../../../main/ets/libs/types';
import { CollaborationApi, TemplateCreateBody, CollaborationStartBody } from '../../../main/ets/libs/api/modules/CollaborationApi';

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

export default function collaborationApiTest() {
  describe('CollaborationApi', () => {
    let client: HttpClient;
    let backend: MockBackend;
    let api: CollaborationApi;

    beforeEach(() => {
      backend = new MockBackend();
      client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      api = new CollaborationApi(client);
    });

    // ========== 协作模板（/collaboration/templates）==========

    it('listTemplates_calls_get_with_limit', 0, () => {
      api.listTemplates(20);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/collaboration/templates')).assertTrue();
      expect(url.includes('limit=20')).assertTrue();
    });

    it('createTemplate_posts_name_description_workflow_participants', 0, () => {
      const workflow: Record<string, Object> = {};
      const body: TemplateCreateBody = {
        name: '模板A', description: 'd', workflow: workflow, participants: ['u1'],
      };
      api.createTemplate(body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/collaboration/templates');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('removeTemplate_deletes_by_id', 0, () => {
      api.removeTemplate('t1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/collaboration/templates/t1');
    });

    // ========== 启动 / 历史 / 会话 / 统计 ==========

    it('startCollaboration_posts_start_contract', 0, () => {
      const context: Record<string, Object> = {};
      const body: CollaborationStartBody = { template_id: 't1', participants: ['u1'], context: context };
      api.startCollaboration(body);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/collaboration/start');
      expect(backend.requests[0].body).assertEqual(body);
    });

    it('listHistory_carries_limit_offset', 0, () => {
      api.listHistory(50, 0);
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('/collaboration/history')).assertTrue();
      expect(url.includes('limit=50')).assertTrue();
      expect(url.includes('offset=0')).assertTrue();
    });

    it('listSessions_gets_collaboration_sessions', 0, () => {
      api.listSessions(50, 0);
      const url = backend.requests[0].url;
      expect(url.includes('/collaboration/sessions')).assertTrue();
    });

    it('getStats_gets_collaboration_stats', 0, () => {
      api.getStats();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/collaboration/stats');
    });

    // ========== 看板任务（/tasks/*）==========

    it('listTasks_first_fetches_boards', 0, () => {
      // /tasks/boards 返回裸数组——给一块看板，模块随后按看板聚合任务
      const board: Record<string, Object> = { 'id': 'b1', 'name': '任务看板' };
      const boards: Record<string, Object>[] = [board];
      backend.responseBody = boards;
      api.listTasks(undefined);
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/tasks/boards');
    });

    it('createTask_first_fetches_boards', 0, async () => {
      // createTask 先取看板（有看板直接落第一个），Partial<Task> 显式类型钉住 status/priority 词汇
      const board: Record<string, Object> = { 'id': 'b1', 'name': '任务看板' };
      const boards: Record<string, Object>[] = [board];
      backend.responseBody = boards;
      const data: Partial<Task> = { title: 'T1', status: 'todo', priority: 'medium' };
      await api.createTask(data);
      expect(backend.requests[0].url).assertEqual('https://api.example.com/tasks/boards');
    });

    it('updateTask_puts_tasks_by_id', 0, () => {
      const body: Record<string, Object> = { 'status': 'done' };
      api.updateTask('task-1', body);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/tasks/task-1');
    });

    it('moveTask_puts_tasks_move', 0, () => {
      const body: Record<string, Object> = { 'status': 'in_progress' };
      api.moveTask('task-1', body);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/tasks/task-1/move');
    });

    // ========== 退役端点：必须 throw 且不发任何请求 ==========
    // P1-35 后 projects/teams/workflows 已接线（/v1/projects、/v1/teams、/v1/neurflow/workflows），
    // 不再退役；任务删除后端无路由（tasks_api 仅提供增查改）——退役面仅剩 removeTask。

    it('retiredTaskDelete_throws_and_fires_no_request', 0, async () => {
      let thrown = '';
      try {
        await api.removeTask('task-1');
      } catch (e) {
        thrown = (e as Error).message;
      }
      expect(thrown.length > 0).assertTrue();
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

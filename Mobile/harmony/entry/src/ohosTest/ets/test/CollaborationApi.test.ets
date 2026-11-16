// CollaborationApi 单元测试 - 真实契约版（M9.2 协作域迁移）
// 后端事实源：/v1/collaboration（templates/start/history/sessions/stats）+ /v1/tasks（看板任务）。
// 旧 /collaboration/projects|teams|workflows 端点不存在：对应方法必须 throw 点名，
// 且**不发任何网络请求**（本文件钉住这一行为）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { ApiResponse } from '../../../../main/ets/libs/types';
import { CollaborationApi } from '../../../../main/ets/libs/api/modules/CollaborationApi';

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
      const body = {
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
      const body = { template_id: 't1', participants: ['u1'], context: context };
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
      api.listTasks(undefined);
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/tasks/boards');
    });

    it('createTask_first_fetches_boards', 0, () => {
      const data = { title: 'T1', status: 'todo', priority: 'medium' };
      api.createTask(data);
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

    it('retiredProjectsTeamsWorkflows_fire_no_request', 0, () => {
      api.listProjects(undefined);
      api.createProject({});
      api.listTeams(undefined);
      api.createTeam({});
      api.listWorkflows(undefined);
      api.createWorkflow({});
      expect(backend.requests.length).assertEqual(0);
    });
  });
}

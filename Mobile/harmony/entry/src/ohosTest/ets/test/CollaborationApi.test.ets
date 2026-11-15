// CollaborationApi 单元测试 - TDD 垂直切片
// 通过 HttpBackend 接口注入 mock，验证 CollaborationApi 调用契约（method/url/body/返回值）
// 覆盖 4 个实体：Project、Team、Task、Workflow（每个 3 个核心测试 = 12 测试）
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import {
  ApiResponse,
  Project,
  Team,
  Task,
  Workflow,
  ProjectStatus,
  TaskStatus,
  TaskPriority,
  WorkflowStatus,
  TeamRole,
  PageResult,
  PageParams,
} from '../../../../main/ets/libs/types';
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

    // ========== Project 实体（3 测试）==========
    it('listProjects_calls_get_projects_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listProjects();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/projects');
    });

    it('createProject_posts_body_to_projects', 0, () => {
      const data: Partial<Project> = { name: 'P1', description: 'desc', status: 'planning' as ProjectStatus, owner: 'u1', members: [] };
      api.createProject(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/projects');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('removeProject_deletes_by_id', 0, () => {
      api.removeProject('p1');
      expect(backend.requests[0].method).assertEqual('DELETE');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/projects/p1');
    });

    // ========== Team 实体（3 测试）==========
    it('listTeams_calls_get_teams_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listTeams({ page: 1, size: 5 });
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('page=1')).assertTrue();
      expect(url.includes('size=5')).assertTrue();
    });

    it('getTeam_calls_get_with_id', 0, () => {
      api.getTeam('t1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/teams/t1');
    });

    it('updateTeam_puts_id_and_body', 0, () => {
      const data: Partial<Team> = { name: 'updated' };
      api.updateTeam('t1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/teams/t1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Task 实体（3 测试）==========
    it('listTasks_filters_by_projectId', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listTasks('p1');
      const url = backend.requests[0].url;
      expect(backend.requests[0].method).assertEqual('GET');
      expect(url.includes('projectId=p1')).assertTrue();
    });

    it('createTask_posts_body_to_tasks', 0, () => {
      const data: Partial<Task> = {
        projectId: 'p1', title: 'T1', status: 'todo' as TaskStatus,
        priority: 'medium' as TaskPriority, tags: [],
      };
      api.createTask(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/tasks');
      expect(backend.requests[0].body).assertEqual(data);
    });

    it('updateTask_puts_to_id_url', 0, () => {
      const data: Partial<Task> = { status: 'done' as TaskStatus };
      api.updateTask('t1', data);
      expect(backend.requests[0].method).assertEqual('PUT');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/tasks/t1');
      expect(backend.requests[0].body).assertEqual(data);
    });

    // ========== Workflow 实体（3 测试）==========
    it('listWorkflows_calls_get_workflows_url', 0, () => {
      backend.response = { code: 0, message: 'ok', data: { items: [], total: 0, page: 1, size: 20 } };
      api.listWorkflows();
      expect(backend.requests[0].method).assertEqual('GET');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/workflows');
    });

    it('getWorkflow_calls_get_with_id', 0, () => {
      api.getWorkflow('w1');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/workflows/w1');
    });

    it('createWorkflow_posts_body_to_workflows', 0, () => {
      const data: Partial<Workflow> = { name: 'W1', status: 'draft' as WorkflowStatus, nodes: [], edges: [], version: '1' };
      api.createWorkflow(data);
      expect(backend.requests[0].method).assertEqual('POST');
      expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/collaboration/workflows');
      expect(backend.requests[0].body).assertEqual(data);
    });
  });
}

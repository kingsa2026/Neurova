/**
 * CollaborationApi - 协作层 API 模块
 *
 * 职责：封装协作域 4 个实体的 CRUD：Project、Team、Task、Workflow
 * 设计：通过 HttpClient 委托请求，不直接依赖 @ohos.net.http；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().collaboration;
 *   const projects = await api.listProjects({ page: 1, size: 10 });
 *   const task = await api.createTask({ projectId: 'p1', title: 'T1', ... });
 */
import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  Project,
  Team,
  Task,
  TaskStatus,
  TaskPriority,
  Workflow,
  PageResult,
  PageParams,
} from '../../types';

/** 创建看板 body（/v1/tasks/boards 契约字段） */
interface CreateBoardBody {
  name: string;
}

/** 创建任务 body（/v1/tasks/boards/{id}/tasks 契约字段） */
interface CreateTaskBody {
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  dueDate: string;
}

export class CollaborationApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  // ========== Project ==========

  /** 列出项目（可选分页） */
  async listProjects(params?: PageParams): Promise<ApiResponse<PageResult<Project>>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Project>>('/v1/collaboration/projects', query);
  }

  /** 获取单个项目 */
  async getProject(id: string): Promise<ApiResponse<Project>> {
    return this.client.get<Project>(`/v1/collaboration/projects/${id}`);
  }

  /** 创建项目 */
  async createProject(data: Partial<Project>): Promise<ApiResponse<Project>> {
    return this.client.post<Project>('/v1/collaboration/projects', data);
  }

  /** 更新项目 */
  async updateProject(id: string, data: Partial<Project>): Promise<ApiResponse<Project>> {
    return this.client.put<Project>(`/v1/collaboration/projects/${id}`, data);
  }

  /** 删除项目 */
  async removeProject(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/collaboration/projects/${id}`);
  }

  // ========== Team ==========

  /** 列出团队（可选分页） */
  async listTeams(params?: PageParams): Promise<ApiResponse<PageResult<Team>>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Team>>('/v1/collaboration/teams', query);
  }

  /** 获取单个团队 */
  async getTeam(id: string): Promise<ApiResponse<Team>> {
    return this.client.get<Team>(`/v1/collaboration/teams/${id}`);
  }

  /** 创建团队 */
  async createTeam(data: Partial<Team>): Promise<ApiResponse<Team>> {
    return this.client.post<Team>('/v1/collaboration/teams', data);
  }

  /** 更新团队 */
  async updateTeam(id: string, data: Partial<Team>): Promise<ApiResponse<Team>> {
    return this.client.put<Team>(`/v1/collaboration/teams/${id}`, data);
  }

  /** 删除团队 */
  async removeTeam(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/collaboration/teams/${id}`);
  }

  // ========== Task ==========

  /**
   * 列出任务：聚合全部看板的任务（真端点 /v1/tasks/boards + /boards/{id}/tasks，
   * 原 /v1/collaboration/tasks 后端不存在）。补齐 FE Task 契约缺省字段。
   */
  async listTasks(projectId?: string): Promise<ApiResponse<PageResult<Task>>> {
    const boardsRes = await this.client.get<Object[]>('/v1/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    const all: Task[] = [];
    for (const b of boards) {
      if (projectId && String(b['id']) !== projectId) {
        continue;
      }
      const boardId = String(b['id']);
      const tasksRes = await this.client.get<Object[]>(`/v1/tasks/boards/${boardId}/tasks`);
      const rows = (tasksRes.data ?? []) as Array<Record<string, Object>>;
      for (const row of rows) {
        all.push({
          id: String(row['id'] ?? ''),
          projectId: boardId,
          title: String(row['title'] ?? ''),
          description: String(row['description'] ?? ''),
          status: String(row['status'] ?? 'todo') as TaskStatus,
          priority: String(row['priority'] ?? 'medium') as TaskPriority,
          assignee: row['assignee'] !== undefined && row['assignee'] !== null ? String(row['assignee']) : undefined,
          dueDate: String(row['dueDate'] ?? ''),
          tags: [],
          createdAt: row['created_at'] !== undefined ? new Date(Number(row['created_at']) * 1000).toISOString() : '',
          updatedAt: row['updated_at'] !== undefined ? new Date(Number(row['updated_at']) * 1000).toISOString() : '',
        });
      }
    }
    return { code: 0, message: 'ok', data: { items: all, total: all.length } } as ApiResponse<PageResult<Task>>;
  }

  /** 创建任务：落到第一个看板（无看板先建默认看板） */
  async createTask(data: Partial<Task>): Promise<ApiResponse<Task>> {
    const boardsRes = await this.client.get<Object[]>('/v1/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    let boardId = boards.length > 0 ? String(boards[0]['id']) : '';
    if (boardId === '') {
      const boardBody: CreateBoardBody = { name: '任务看板' };
      const created = await this.client.post<Object>('/v1/tasks/boards', boardBody);
      boardId = String((created.data as Record<string, Object>)['id'] ?? '');
    }
    const body: CreateTaskBody = {
      title: data.title ?? '',
      description: data.description ?? '',
      status: data.status ?? 'todo',
      priority: data.priority ?? 'medium',
      dueDate: data.dueDate ?? '',
    };
    const res = await this.client.post<Object>(`/v1/tasks/boards/${boardId}/tasks`, body);
    const row = (res.data ?? {}) as Record<string, Object>;
    return {
      code: res.code, message: res.message,
      data: {
        id: String(row['id'] ?? ''), projectId: boardId, title: String(row['title'] ?? ''),
        description: String(row['description'] ?? ''), status: String(row['status'] ?? 'todo') as TaskStatus,
        priority: String(row['priority'] ?? 'medium') as TaskPriority,
        dueDate: String(row['dueDate'] ?? ''), tags: [],
        createdAt: '', updatedAt: '',
      },
    } as ApiResponse<Task>;
  }

  /** 删除任务：真端点 DELETE /v1/tasks/boards/{boardId}/tasks/{taskId}（任务挂在看板下，看板解析与 createTask 同源） */
  async removeTask(id: string): Promise<ApiResponse<Object>> {
    const boardsRes = await this.client.get<Object[]>('/v1/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    if (boards.length === 0) {
      return { code: 1, message: '任务看板不存在，无法删除任务', data: '' } as ApiResponse<Object>;
    }
    const boardId = String(boards[0]['id']);
    return this.client.delete<Object>(`/v1/tasks/boards/${boardId}/tasks/${id}`);
  }

  // ========== Workflow ==========

  /** 列出工作流（可选分页） */
  async listWorkflows(params?: PageParams): Promise<ApiResponse<PageResult<Workflow>>> {
    const query: Record<string, Object> = {};
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Workflow>>('/v1/collaboration/workflows', query);
  }

  /** 获取单个工作流 */
  async getWorkflow(id: string): Promise<ApiResponse<Workflow>> {
    return this.client.get<Workflow>(`/v1/collaboration/workflows/${id}`);
  }

  /** 创建工作流 */
  async createWorkflow(data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    return this.client.post<Workflow>('/v1/collaboration/workflows', data);
  }

  /** 更新工作流 */
  async updateWorkflow(id: string, data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    return this.client.put<Workflow>(`/v1/collaboration/workflows/${id}`, data);
  }

  /** 删除工作流 */
  async removeWorkflow(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/collaboration/workflows/${id}`);
  }
}

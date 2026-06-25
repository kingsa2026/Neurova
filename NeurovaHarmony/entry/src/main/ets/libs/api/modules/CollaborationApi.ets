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
  Workflow,
  PageResult,
  PageParams,
} from '../../types';

export class CollaborationApi {
  constructor(private client: HttpClient) {}

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

  /** 列出任务（可选 projectId 过滤 + 分页） */
  async listTasks(
    projectId?: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Task>>> {
    const query: Record<string, Object> = {};
    if (projectId) query['projectId'] = projectId;
    if (params) {
      if (params.page !== undefined) query['page'] = params.page;
      if (params.size !== undefined) query['size'] = params.size;
    }
    return this.client.get<PageResult<Task>>('/v1/collaboration/tasks', query);
  }

  /** 获取单个任务 */
  async getTask(id: string): Promise<ApiResponse<Task>> {
    return this.client.get<Task>(`/v1/collaboration/tasks/${id}`);
  }

  /** 创建任务 */
  async createTask(data: Partial<Task>): Promise<ApiResponse<Task>> {
    return this.client.post<Task>('/v1/collaboration/tasks', data);
  }

  /** 更新任务 */
  async updateTask(id: string, data: Partial<Task>): Promise<ApiResponse<Task>> {
    return this.client.put<Task>(`/v1/collaboration/tasks/${id}`, data);
  }

  /** 删除任务 */
  async removeTask(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/collaboration/tasks/${id}`);
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

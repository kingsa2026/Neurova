/**
 * CollaborationApi - 协作域 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   collaboration_api.py @ /v1/collaboration：
 *     GET/POST /templates、GET/PUT/DELETE /templates/{id}（模板=项目投影）
 *     POST /start {template_id?,participants,context} → data={collaboration_id,template_id,participants}
 *     GET /history?limit=&offset= → data={history:[...],total}
 *     GET /sessions?limit=&offset= → data=[...]
 *     GET /stats → data={projects,templates,sessions,workflows}
 *   tasks_api.py @ /v1/tasks：
 *     GET/POST /boards、GET /boards/{id}、GET/POST /boards/{id}/tasks、
 *     PUT /tasks/{id}、PUT /tasks/{id}/move、GET /boards/{id}/stats
 * 旧 /collaboration/projects|teams|workflows 后端不存在（协作实体实为模板/会话/历史/
 * 统计/看板任务）：对应方法一律 throw 点名，不再发往不存在的路由。
 */

import { HttpClient } from '../HttpClient';
import {
  ApiResponse,
  Task,
  TaskStatus,
  TaskPriority,
  Project,
  Team,
  Workflow,
  PageResult,
  PageParams,
} from '../../types';

/** 协作模板（collaboration_api.CollaborationTemplate 投影） */
export interface CollaborationTemplateDto {
  template_id: string;
  name: string;
  description: string;
  workflow: Record<string, Object>;
  participants: string[];
  created_at: string;
  updated_at: string;
}

/** 协作历史条目（collaboration_api.get_collaboration_history data.history 投影） */
export interface CollaborationHistoryDto {
  id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
  members: string[];
  owner_id: string;
}

/** 协作会话（collaboration_api.list_collaboration_sessions data 投影） */
export interface CollaborationSessionDto {
  id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
  members: string[];
  owner_id: string;
}

/** 协作概览统计（collaboration_api.get_collaboration_stats data 投影） */
export interface CollaborationStatsDto {
  projects: number;
  templates: number;
  sessions: number;
  workflows: number;
}

/** 启动协作结果（collaboration_api.start_collaboration data 投影） */
export interface CollaborationStartResultDto {
  collaboration_id: string;
  template_id: string | null;
  participants: string[];
}

/** 创建协作模板 body（CollaborationTemplateCreate 契约） */
export interface TemplateCreateBody {
  name: string;
  description: string;
  workflow: Record<string, Object>;
  participants: string[];
}

/** 启动协作 body（CollaborationStart 契约） */
export interface CollaborationStartBody {
  template_id?: string;
  participants: string[];
  context: Record<string, Object>;
}

/** 创建看板 body（/tasks/boards 契约字段） */
interface CreateBoardBody {
  name: string;
}

/** 创建任务 body（/tasks/boards/{id}/tasks 契约字段） */
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

  // ========== 协作模板（真实端点 /collaboration/templates）==========

  /** 协作模板列表（GET /collaboration/templates?limit=，裸数组） */
  async listTemplates(limit?: number): Promise<ApiResponse<CollaborationTemplateDto[]>> {
    const query: Record<string, Object> = {};
    if (limit !== undefined) query['limit'] = limit;
    return this.client.get<CollaborationTemplateDto[]>('/collaboration/templates', query);
  }

  /** 创建协作模板（POST /collaboration/templates） */
  async createTemplate(body: TemplateCreateBody): Promise<ApiResponse<CollaborationTemplateDto>> {
    return this.client.post<CollaborationTemplateDto>('/collaboration/templates', body);
  }

  /** 协作模板详情（GET /collaboration/templates/{id}） */
  async getTemplate(templateId: string): Promise<ApiResponse<CollaborationTemplateDto>> {
    return this.client.get<CollaborationTemplateDto>(`/collaboration/templates/${templateId}`);
  }

  /** 更新协作模板（PUT /collaboration/templates/{id}） */
  async updateTemplate(templateId: string, body: TemplateCreateBody): Promise<ApiResponse<CollaborationTemplateDto>> {
    return this.client.put<CollaborationTemplateDto>(`/collaboration/templates/${templateId}`, body);
  }

  /** 删除协作模板（DELETE /collaboration/templates/{id}） */
  async removeTemplate(templateId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/collaboration/templates/${templateId}`);
  }

  // ========== 启动 / 历史 / 会话 / 统计（真实端点）==========

  /** 启动协作（POST /collaboration/start，data 投影回结构体） */
  async startCollaboration(body: CollaborationStartBody): Promise<ApiResponse<CollaborationStartResultDto>> {
    const res = await this.client.post<Object>('/collaboration/start', body);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const result: CollaborationStartResultDto = {
      collaboration_id: String(payload['collaboration_id'] ?? ''),
      template_id: payload['template_id'] !== undefined && payload['template_id'] !== null
        ? String(payload['template_id']) : null,
      participants: (payload['participants'] ?? []) as string[],
    };
    return { code: res.code, message: res.message, data: result } as ApiResponse<CollaborationStartResultDto>;
  }

  /** 协作历史（GET /collaboration/history，data={history,total} 拆包成 PageResult） */
  async listHistory(limit?: number, offset?: number): Promise<ApiResponse<PageResult<CollaborationHistoryDto>>> {
    const query: Record<string, Object> = {};
    if (limit !== undefined) query['limit'] = limit;
    if (offset !== undefined) query['offset'] = offset;
    const res = await this.client.get<Object>('/collaboration/history', query);
    const payload = (res.data ?? {}) as Record<string, Object>;
    const items = (payload['history'] ?? []) as CollaborationHistoryDto[];
    const total = Number(payload['total'] ?? items.length);
    return {
      code: res.code, message: res.message,
      data: { items: items, total: total, page: 1, size: items.length },
    } as ApiResponse<PageResult<CollaborationHistoryDto>>;
  }

  /** 协作会话列表（GET /collaboration/sessions，data 为数组） */
  async listSessions(limit?: number, offset?: number): Promise<ApiResponse<CollaborationSessionDto[]>> {
    const query: Record<string, Object> = {};
    if (limit !== undefined) query['limit'] = limit;
    if (offset !== undefined) query['offset'] = offset;
    const res = await this.client.get<Object>('/collaboration/sessions', query);
    const payload = (res.data ?? []) as CollaborationSessionDto[];
    return { code: res.code, message: res.message, data: payload } as ApiResponse<CollaborationSessionDto[]>;
  }

  /** 协作概览统计（GET /collaboration/stats，data 投影回结构体） */
  async getStats(): Promise<ApiResponse<CollaborationStatsDto>> {
    const res = await this.client.get<Object>('/collaboration/stats');
    const payload = (res.data ?? {}) as Record<string, Object>;
    const stats: CollaborationStatsDto = {
      projects: Number(payload['projects'] ?? 0),
      templates: Number(payload['templates'] ?? 0),
      sessions: Number(payload['sessions'] ?? 0),
      workflows: Number(payload['workflows'] ?? 0),
    };
    return { code: res.code, message: res.message, data: stats } as ApiResponse<CollaborationStatsDto>;
  }

  // ========== 看板任务（真实端点 /tasks/*）==========

  /**
   * 列出任务：聚合全部看板的任务（真端点 /tasks/boards + /boards/{id}/tasks，
   * 原 /v1/collaboration/tasks 后端不存在）。补齐 FE Task 契约缺省字段。
   */
  async listTasks(projectId?: string): Promise<ApiResponse<PageResult<Task>>> {
    const boardsRes = await this.client.get<Object[]>('/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    const all: Task[] = [];
    for (const b of boards) {
      if (projectId && String(b['id']) !== projectId) {
        continue;
      }
      const boardId = String(b['id']);
      const tasksRes = await this.client.get<Object[]>(`/tasks/boards/${boardId}/tasks`);
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
    const boardsRes = await this.client.get<Object[]>('/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    let boardId = boards.length > 0 ? String(boards[0]['id']) : '';
    if (boardId === '') {
      const boardBody: CreateBoardBody = { name: '任务看板' };
      const created = await this.client.post<Object>('/tasks/boards', boardBody);
      boardId = String((created.data as Record<string, Object>)['id'] ?? '');
    }
    const body: CreateTaskBody = {
      title: data.title ?? '',
      description: data.description ?? '',
      status: data.status ?? 'todo',
      priority: data.priority ?? 'medium',
      dueDate: data.dueDate ?? '',
    };
    const res = await this.client.post<Object>(`/tasks/boards/${boardId}/tasks`, body);
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

  /** 更新任务（PUT /tasks/{id}，body 直传后端契约字段） */
  async updateTask(taskId: string, body: Record<string, Object>): Promise<ApiResponse<Task>> {
    return this.client.put<Task>(`/tasks/${taskId}`, body);
  }

  /** 移动任务（看板内拖拽/状态流转，PUT /tasks/{id}/move） */
  async moveTask(taskId: string, body: Record<string, Object>): Promise<ApiResponse<Task>> {
    return this.client.put<Task>(`/tasks/${taskId}/move`, body);
  }

  /** 看板统计（GET /tasks/boards/{id}/stats） */
  async getBoardStats(boardId: string): Promise<ApiResponse<Object>> {
    return this.client.get<Object>(`/tasks/boards/${boardId}/stats`);
  }

  /** 删除任务：真端点 DELETE /tasks/boards/{boardId}/tasks/{taskId}（任务挂在看板下，看板解析与 createTask 同源） */
  async removeTask(id: string): Promise<ApiResponse<Object>> {
    const boardsRes = await this.client.get<Object[]>('/tasks/boards');
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    if (boards.length === 0) {
      return { code: 1, message: '任务看板不存在，无法删除任务', data: '' } as ApiResponse<Object>;
    }
    const boardId = String(boards[0]['id']);
    return this.client.delete<Object>(`/tasks/boards/${boardId}/tasks/${id}`);
  }

  // ========== Project / Team / Workflow（后端无此端点，保留原签名抛错点名）==========

  /** @deprecated 后端无 GET /collaboration/projects（协作实体实为 templates/sessions/history/stats） */
  async listProjects(params?: PageParams): Promise<ApiResponse<PageResult<Project>>> {
    throw new Error('后端无此端点：GET /v1/collaboration/projects（协作域实际提供 templates/start/history/sessions/stats）');
  }

  /** @deprecated 后端无 GET /collaboration/projects/{id} */
  async getProject(id: string): Promise<ApiResponse<Project>> {
    throw new Error('后端无此端点：GET /v1/collaboration/projects/{id}');
  }

  /** @deprecated 后端无 POST /collaboration/projects */
  async createProject(data: Partial<Project>): Promise<ApiResponse<Project>> {
    throw new Error('后端无此端点：POST /v1/collaboration/projects');
  }

  /** @deprecated 后端无 PUT /collaboration/projects/{id} */
  async updateProject(id: string, data: Partial<Project>): Promise<ApiResponse<Project>> {
    throw new Error('后端无此端点：PUT /v1/collaboration/projects/{id}');
  }

  /** @deprecated 后端无 DELETE /collaboration/projects/{id} */
  async removeProject(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/collaboration/projects/{id}');
  }

  /** @deprecated 后端无 GET /collaboration/teams */
  async listTeams(params?: PageParams): Promise<ApiResponse<PageResult<Team>>> {
    throw new Error('后端无此端点：GET /v1/collaboration/teams（协作域无团队实体）');
  }

  /** @deprecated 后端无 GET /collaboration/teams/{id} */
  async getTeam(id: string): Promise<ApiResponse<Team>> {
    throw new Error('后端无此端点：GET /v1/collaboration/teams/{id}');
  }

  /** @deprecated 后端无 POST /collaboration/teams */
  async createTeam(data: Partial<Team>): Promise<ApiResponse<Team>> {
    throw new Error('后端无此端点：POST /v1/collaboration/teams');
  }

  /** @deprecated 后端无 PUT /collaboration/teams/{id} */
  async updateTeam(id: string, data: Partial<Team>): Promise<ApiResponse<Team>> {
    throw new Error('后端无此端点：PUT /v1/collaboration/teams/{id}');
  }

  /** @deprecated 后端无 DELETE /collaboration/teams/{id} */
  async removeTeam(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/collaboration/teams/{id}');
  }

  /** @deprecated 后端无 GET /collaboration/workflows（工作流计数经 /collaboration/stats） */
  async listWorkflows(params?: PageParams): Promise<ApiResponse<PageResult<Workflow>>> {
    throw new Error('后端无此端点：GET /v1/collaboration/workflows（工作流计数走 /v1/collaboration/stats）');
  }

  /** @deprecated 后端无 GET /collaboration/workflows/{id} */
  async getWorkflow(id: string): Promise<ApiResponse<Workflow>> {
    throw new Error('后端无此端点：GET /v1/collaboration/workflows/{id}');
  }

  /** @deprecated 后端无 POST /collaboration/workflows */
  async createWorkflow(data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    throw new Error('后端无此端点：POST /v1/collaboration/workflows');
  }

  /** @deprecated 后端无 PUT /collaboration/workflows/{id} */
  async updateWorkflow(id: string, data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    throw new Error('后端无此端点：PUT /v1/collaboration/workflows/{id}');
  }

  /** @deprecated 后端无 DELETE /collaboration/workflows/{id} */
  async removeWorkflow(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/collaboration/workflows/{id}');
  }
}

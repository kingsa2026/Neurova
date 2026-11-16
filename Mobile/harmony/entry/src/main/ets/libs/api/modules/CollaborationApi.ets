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
 *     PUT /tasks/{id}、PUT /tasks/{id}/move、GET /boards/{id}/stats（全部裸形状，边界归一）
 *   projects_api.py @ /v1/projects：GET/POST ""、GET/PUT/DELETE /{id}（P1-35 接线）
 *   teams_api.py @ /v1/teams：GET/POST ""、GET/PUT/DELETE /{id}（P1-35 接线）
 *   neurflow_api.py @ /v1/neurflow/workflows：GET/POST ""、GET/PUT/DELETE /{id}
 *     （P1-35 接线；{workflow:...} 裸 dict 边界归一）
 * 旧 /collaboration/projects|teams|workflows 路径后端不存在——实体面在
 * /v1/projects、/v1/teams、/v1/neurflow/workflows；任务删除后端无路由，诚实 throw。
 */

import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import {
  ApiResponse,
  Task,
  TaskStatus,
  TaskPriority,
  Project,
  ProjectStatus,
  Team,
  TeamMember,
  TeamRole,
  Workflow,
  WorkflowStatus,
  WorkflowNode,
  WorkflowEdge,
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

/** 项目（projects_api.ProjectInfo 投影） */
interface ProjectInfoDto {
  project_id: string;
  name: string;
  description: string;
  status: string;
  owner_id: string;
  teams_count: number;
  tasks_count: number;
  created_at: number;
  updated_at: number;
}

/** 团队（teams_api.TeamInfo 投影） */
interface TeamInfoDto {
  id: string;
  name: string;
  description: string;
  project_id: string | null;
  owner_id: string;
  members: string[];
  members_detail: Array<Record<string, Object>>;
  created_at: number;
  updated_at: number;
}

/** 工作流（neurflow WorkflowDefinition.to_dict 投影） */
interface WorkflowDto {
  id: string;
  name: string;
  description: string;
  version: string;
  status: string;
  nodes: Object[];
  edges: Object[];
  created_at: number;
  updated_at: number;
}

/** 秒级时间戳 → ISO 字符串（空值/0 回退 ''） */
function tsToIso(ts: number | null | undefined): string {
  if (ts === null || ts === undefined || ts <= 0) return '';
  return new Date(ts * 1000).toISOString();
}

/** 裸数组 → PageResult 本地分页（page 默认 1、size 默认 20） */
function pageOf<T>(arr: T[], params?: PageParams): PageResult<T> {
  const page = params && params.page !== undefined ? params.page : 1;
  const size = params && params.size !== undefined ? params.size : 20;
  const start = (Math.max(page, 1) - 1) * size;
  const items = arr.slice(start, start + size);
  const result: PageResult<T> = { items: items, total: arr.length, page: page, size: size };
  return result;
}

/** 后端项目状态 → 前端 ProjectStatus（未知值回落 active） */
function normProjectStatus(status: string): ProjectStatus {
  if (status === 'planning' || status === 'active' || status === 'paused'
    || status === 'completed' || status === 'archived') {
    return status;
  }
  return 'active';
}

/** 后端工作流状态 → 前端 WorkflowStatus（published/running→active；未知回落 draft） */
function normWorkflowStatus(status: string): WorkflowStatus {
  if (status === 'draft') return 'draft';
  if (status === 'published' || status === 'running') return 'active';
  if (status === 'paused') return 'paused';
  if (status === 'archived') return 'archived';
  return 'draft';
}

/** 前端工作流状态 → 后端词汇（active→published） */
function workflowStatusToBackend(status: WorkflowStatus): string {
  if (status === 'active') return 'published';
  return status;
}

/** ProjectInfo → Project（单源映射；成员清单不在 ProjectInfo 里，诚实空数组） */
function toProject(dto: ProjectInfoDto): Project {
  const project: Project = {
    id: dto.project_id,
    name: dto.name,
    description: dto.description,
    status: normProjectStatus(dto.status),
    owner: dto.owner_id,
    members: [],
    createdAt: tsToIso(dto.created_at),
    updatedAt: tsToIso(dto.updated_at),
  };
  return project;
}

/** TeamInfo → Team（单源映射；成员角色以 members_detail 为准，缺省 member） */
function toTeam(dto: TeamInfoDto): Team {
  const members: TeamMember[] = [];
  if (dto.members_detail && dto.members_detail.length > 0) {
    for (const detail of dto.members_detail) {
      const member: TeamMember = {
        userId: String(detail['user_id'] ?? ''),
        role: String(detail['role'] ?? 'member') as TeamRole,
      };
      members.push(member);
    }
  } else {
    for (const userId of dto.members) {
      const member: TeamMember = { userId: userId, role: 'member' };
      members.push(member);
    }
  }
  const team: Team = {
    id: dto.id,
    name: dto.name,
    description: dto.description,
    members: members,
    createdAt: tsToIso(dto.created_at),
  };
  return team;
}

/** WorkflowDefinition → Workflow（单源映射；nodes/edges 原样透传） */
function toWorkflow(dto: WorkflowDto): Workflow {
  const workflow: Workflow = {
    id: dto.id,
    name: dto.name,
    description: dto.description,
    status: normWorkflowStatus(dto.status),
    nodes: dto.nodes as Object[] as WorkflowNode[],
    edges: dto.edges as Object[] as WorkflowEdge[],
    version: dto.version,
    createdAt: tsToIso(dto.created_at),
    updatedAt: tsToIso(dto.updated_at),
  };
  return workflow;
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

  // ========== 协作模板（真实端点 /collaboration/templates；裸形状边界归一）==========

  /** 协作模板列表（GET /collaboration/templates?limit=，后端裸数组边界归一） */
  async listTemplates(limit?: number): Promise<ApiResponse<CollaborationTemplateDto[]>> {
    const query: Record<string, Object> = {};
    if (limit !== undefined) query['limit'] = limit;
    const res = await this.client.get<CollaborationTemplateDto[]>('/collaboration/templates', query);
    return asEnvelopeList<CollaborationTemplateDto>(res as ApiResponse<CollaborationTemplateDto[]>);
  }

  /** 创建协作模板（POST /collaboration/templates，CollaborationTemplate 裸对象边界归一） */
  async createTemplate(body: TemplateCreateBody): Promise<ApiResponse<CollaborationTemplateDto>> {
    const res = await this.client.post<CollaborationTemplateDto>('/collaboration/templates', body);
    return asEnvelope<CollaborationTemplateDto>(res, ['template_id', 'name']);
  }

  /** 协作模板详情（GET /collaboration/templates/{id}，裸对象边界归一） */
  async getTemplate(templateId: string): Promise<ApiResponse<CollaborationTemplateDto>> {
    const res = await this.client.get<CollaborationTemplateDto>(`/collaboration/templates/${templateId}`);
    return asEnvelope<CollaborationTemplateDto>(res, ['template_id', 'name']);
  }

  /** 更新协作模板（PUT /collaboration/templates/{id}，裸对象边界归一） */
  async updateTemplate(templateId: string, body: TemplateCreateBody): Promise<ApiResponse<CollaborationTemplateDto>> {
    const res = await this.client.put<CollaborationTemplateDto>(`/collaboration/templates/${templateId}`, body);
    return asEnvelope<CollaborationTemplateDto>(res, ['template_id', 'name']);
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

  // ========== 看板任务（真实端点 /tasks/*；裸形状边界归一）==========

  /**
   * 列出任务：聚合全部看板的任务（真端点 /tasks/boards + /boards/{id}/tasks，
   * 原 /v1/collaboration/tasks 后端不存在）。看板/任务均为裸形状，边界归一后补齐 FE Task 契约缺省字段。
   */
  async listTasks(projectId?: string): Promise<ApiResponse<PageResult<Task>>> {
    const boardsRes = asEnvelopeList<Object>(await this.client.get<Object[]>('/tasks/boards'));
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    const all: Task[] = [];
    for (const b of boards) {
      if (projectId && String(b['id']) !== projectId) {
        continue;
      }
      const boardId = String(b['id']);
      const tasksRes = asEnvelopeList<Object>(await this.client.get<Object[]>(`/tasks/boards/${boardId}/tasks`));
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

  /** 创建任务：落到第一个看板（无看板先建默认看板；看板/任务裸对象边界归一） */
  async createTask(data: Partial<Task>): Promise<ApiResponse<Task>> {
    const boardsRes = asEnvelopeList<Object>(await this.client.get<Object[]>('/tasks/boards'));
    const boards = (boardsRes.data ?? []) as Array<Record<string, Object>>;
    let boardId = boards.length > 0 ? String(boards[0]['id']) : '';
    if (boardId === '') {
      const boardBody: CreateBoardBody = { name: '任务看板' };
      const created = asEnvelope<Object>(await this.client.post<Object>('/tasks/boards', boardBody), ['id', 'name']);
      boardId = String(((created.data ?? {}) as Record<string, Object>)['id'] ?? '');
    }
    const body: CreateTaskBody = {
      title: data.title ?? '',
      description: data.description ?? '',
      status: data.status ?? 'todo',
      priority: data.priority ?? 'medium',
      dueDate: data.dueDate ?? '',
    };
    const res = asEnvelope<Object>(await this.client.post<Object>(`/tasks/boards/${boardId}/tasks`, body), ['id', 'title']);
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

  /** 更新任务（PUT /tasks/{id}，TaskInfo 裸对象边界归一，body 直传后端契约字段） */
  async updateTask(taskId: string, body: Record<string, Object>): Promise<ApiResponse<Task>> {
    const res = await this.client.put<Task>(`/tasks/${taskId}`, body);
    return asEnvelope<Task>(res, ['id', 'title']);
  }

  /** 移动任务（看板内拖拽/状态流转，PUT /tasks/{id}/move，TaskInfo 裸对象边界归一） */
  async moveTask(taskId: string, body: Record<string, Object>): Promise<ApiResponse<Task>> {
    const res = await this.client.put<Task>(`/tasks/${taskId}/move`, body);
    return asEnvelope<Task>(res, ['id', 'title']);
  }

  /** 看板统计（GET /tasks/boards/{id}/stats，BoardStats 裸对象边界归一） */
  async getBoardStats(boardId: string): Promise<ApiResponse<Object>> {
    const res = await this.client.get<Object>(`/tasks/boards/${boardId}/stats`);
    return asEnvelope<Object>(res, ['board_id', 'total_tasks']) as ApiResponse<Object>;
  }

  /** 删除任务：后端 /v1/tasks 无 DELETE 路由（tasks_api.py 仅 boards/tasks 的增查改）——诚实失败点名 */
  async removeTask(id: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：DELETE /v1/tasks/...（tasks_api 未提供任务删除路由，任务只能改状态不能删）');
  }

  // ========== Project / Team / Workflow（P1-35 接线：projects→/v1/projects、
  // teams→/v1/teams、workflows→/v1/neurflow/workflows，均后端真实存在）==========

  /** 项目列表（GET /v1/projects，ProjectInfo 裸数组边界归一后映射+本地分页） */
  async listProjects(params?: PageParams): Promise<ApiResponse<PageResult<Project>>> {
    const res = asEnvelopeList<ProjectInfoDto>(await this.client.get<ProjectInfoDto[]>('/projects'));
    const arr = (res.data ?? []) as ProjectInfoDto[];
    const projects: Project[] = [];
    for (const dto of arr) {
      projects.push(toProject(dto));
    }
    return { code: res.code, message: res.message, data: pageOf(projects, params) } as ApiResponse<PageResult<Project>>;
  }

  /** 项目详情（GET /v1/projects/{id}，ProjectInfo 裸对象边界归一） */
  async getProject(id: string): Promise<ApiResponse<Project>> {
    const res = await this.client.get<ProjectInfoDto>(`/projects/${id}`);
    const ok = asEnvelope<ProjectInfoDto>(res, ['project_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '项目获取失败');
    }
    return { code: ok.code, message: ok.message, data: toProject(ok.data as Object as ProjectInfoDto) } as ApiResponse<Project>;
  }

  /** 创建项目（POST /v1/projects {name,description}，ProjectInfo 裸对象边界归一） */
  async createProject(data: Partial<Project>): Promise<ApiResponse<Project>> {
    const body: Record<string, Object> = {
      'name': data.name ?? '',
      'description': data.description ?? '',
    };
    const res = await this.client.post<ProjectInfoDto>('/projects', body);
    const ok = asEnvelope<ProjectInfoDto>(res, ['project_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '项目创建失败');
    }
    return { code: ok.code, message: ok.message, data: toProject(ok.data as Object as ProjectInfoDto) } as ApiResponse<Project>;
  }

  /** 更新项目（PUT /v1/projects/{id}，ProjectUpdate 契约 {name?,description?,status?}） */
  async updateProject(id: string, data: Partial<Project>): Promise<ApiResponse<Project>> {
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['name'] = data.name;
    if (data.description !== undefined) body['description'] = data.description;
    if (data.status !== undefined) body['status'] = data.status;
    const res = await this.client.put<ProjectInfoDto>(`/projects/${id}`, body);
    const ok = asEnvelope<ProjectInfoDto>(res, ['project_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '项目更新失败');
    }
    return { code: ok.code, message: ok.message, data: toProject(ok.data as Object as ProjectInfoDto) } as ApiResponse<Project>;
  }

  /** 删除项目（DELETE /v1/projects/{id}，后端返 {code,message} 信封） */
  async removeProject(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/projects/${id}`);
  }

  /** 团队列表（GET /v1/teams，TeamInfo 裸数组边界归一后映射+本地分页） */
  async listTeams(params?: PageParams): Promise<ApiResponse<PageResult<Team>>> {
    const res = asEnvelopeList<TeamInfoDto>(await this.client.get<TeamInfoDto[]>('/teams'));
    const arr = (res.data ?? []) as TeamInfoDto[];
    const teams: Team[] = [];
    for (const dto of arr) {
      teams.push(toTeam(dto));
    }
    return { code: res.code, message: res.message, data: pageOf(teams, params) } as ApiResponse<PageResult<Team>>;
  }

  /** 团队详情（GET /v1/teams/{id}，TeamInfo 裸对象边界归一） */
  async getTeam(id: string): Promise<ApiResponse<Team>> {
    const res = await this.client.get<TeamInfoDto>(`/teams/${id}`);
    const ok = asEnvelope<TeamInfoDto>(res, ['id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '团队获取失败');
    }
    return { code: ok.code, message: ok.message, data: toTeam(ok.data as Object as TeamInfoDto) } as ApiResponse<Team>;
  }

  /** 创建团队（POST /v1/teams {name,description,project_id?}，TeamInfo 裸对象边界归一） */
  async createTeam(data: Partial<Team>): Promise<ApiResponse<Team>> {
    const body: Record<string, Object> = {
      'name': data.name ?? '',
      'description': data.description ?? '',
    };
    const res = await this.client.post<TeamInfoDto>('/teams', body);
    const ok = asEnvelope<TeamInfoDto>(res, ['id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '团队创建失败');
    }
    return { code: ok.code, message: ok.message, data: toTeam(ok.data as Object as TeamInfoDto) } as ApiResponse<Team>;
  }

  /** 更新团队（PUT /v1/teams/{id}，TeamUpdate 契约 {name?,description?}） */
  async updateTeam(id: string, data: Partial<Team>): Promise<ApiResponse<Team>> {
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['name'] = data.name;
    if (data.description !== undefined) body['description'] = data.description;
    const res = await this.client.put<TeamInfoDto>(`/teams/${id}`, body);
    const ok = asEnvelope<TeamInfoDto>(res, ['id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '团队更新失败');
    }
    return { code: ok.code, message: ok.message, data: toTeam(ok.data as Object as TeamInfoDto) } as ApiResponse<Team>;
  }

  /** 删除团队（DELETE /v1/teams/{id}，后端返 {code,message} 信封） */
  async removeTeam(id: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/teams/${id}`);
  }

  /** 工作流列表（GET /v1/neurflow/workflows，{workflows,total} 裸 dict 边界归一后映射+本地分页） */
  async listWorkflows(params?: PageParams): Promise<ApiResponse<PageResult<Workflow>>> {
    const res = asEnvelope<Object>(await this.client.get<Object>('/neurflow/workflows'), ['workflows', 'total']);
    if (res.code !== 0 || !res.data) {
      throw new Error(res.message && res.message.length > 0 ? res.message : '工作流列表获取失败');
    }
    const rows = ((res.data as Record<string, Object>)['workflows'] ?? []) as WorkflowDto[];
    const workflows: Workflow[] = [];
    for (const dto of rows) {
      workflows.push(toWorkflow(dto));
    }
    return { code: res.code, message: res.message, data: pageOf(workflows, params) } as ApiResponse<PageResult<Workflow>>;
  }

  /** 工作流详情（GET /v1/neurflow/workflows/{id}，{workflow:...} 裸 dict 边界归一） */
  async getWorkflow(id: string): Promise<ApiResponse<Workflow>> {
    const res = await this.client.get<Object>(`/neurflow/workflows/${id}`);
    const ok = asEnvelope<Object>(res, ['workflow']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '工作流获取失败');
    }
    const dto = ((ok.data as Record<string, Object>)['workflow'] ?? {}) as WorkflowDto;
    return { code: ok.code, message: ok.message, data: toWorkflow(dto) } as ApiResponse<Workflow>;
  }

  /** 创建工作流（POST /v1/neurflow/workflows，body 为工作流定义 dict；返回 {workflow} 边界归一） */
  async createWorkflow(data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    const body: Record<string, Object> = {
      'name': data.name ?? '',
      'description': data.description ?? '',
      'status': workflowStatusToBackend(data.status ?? 'draft'),
      'nodes': (data.nodes ?? []) as Object[],
      'edges': (data.edges ?? []) as Object[],
      'version': data.version ?? '0.1.0',
    };
    const res = await this.client.post<Object>('/neurflow/workflows', body);
    const ok = asEnvelope<Object>(res, ['workflow']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '工作流创建失败');
    }
    const dto = ((ok.data as Record<string, Object>)['workflow'] ?? {}) as WorkflowDto;
    return { code: ok.code, message: ok.message, data: toWorkflow(dto) } as ApiResponse<Workflow>;
  }

  /** 更新工作流（PUT /v1/neurflow/workflows/{id}；FE active↔paused 切换映射到 published/paused） */
  async updateWorkflow(id: string, data: Partial<Workflow>): Promise<ApiResponse<Workflow>> {
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['name'] = data.name;
    if (data.description !== undefined) body['description'] = data.description;
    if (data.status !== undefined) body['status'] = workflowStatusToBackend(data.status);
    if (data.nodes !== undefined) body['nodes'] = data.nodes as Object[];
    if (data.edges !== undefined) body['edges'] = data.edges as Object[];
    const res = await this.client.put<Object>(`/neurflow/workflows/${id}`, body);
    const ok = asEnvelope<Object>(res, ['workflow']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '工作流更新失败');
    }
    const dto = ((ok.data as Record<string, Object>)['workflow'] ?? {}) as WorkflowDto;
    return { code: ok.code, message: ok.message, data: toWorkflow(dto) } as ApiResponse<Workflow>;
  }

  /** 删除工作流（DELETE /v1/neurflow/workflows/{id}，后端返 {message} 裸 dict 边界归一） */
  async removeWorkflow(id: string): Promise<ApiResponse<Object>> {
    const res = await this.client.delete<Object>(`/neurflow/workflows/${id}`);
    return asEnvelope<Object>(res, ['message']) as ApiResponse<Object>;
  }
}

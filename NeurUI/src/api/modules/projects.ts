import api from '@/api'

// ---------------------------------------------------------------------------
// Types（对齐后端 projects_api.py 契约）
// ---------------------------------------------------------------------------

/** 项目信息（后端 ProjectInfo） */
export interface ProjectInfo {
  project_id: string
  name: string
  description?: string
  status: string
  owner_id?: string
  teams_count?: number
  tasks_count?: number
  created_at?: number
  updated_at?: number
}

/** ProjectPage 视图别名：兼容本地 id 回退与展示用 memberCount/progress/activities */
export type Project = ProjectInfo & {
  id?: string
  memberCount?: number
  progress?: number
  activities?: string[]
}

/** 项目团队（后端 collaboration_isolation.ProjectTeam） */
export interface ProjectTeamDto {
  team_id: string
  name: string
  description?: string
  /** {agent_id: {agent_name, role}} */
  members: Record<string, { agent_name?: string; role?: string }>
  created_at?: number
}

/** 项目任务（后端 collaboration_isolation.ProjectTask） */
export interface ProjectTaskDto {
  task_id: string
  name: string
  workflow_id: string
  /** {type: cron|interval, cron?, interval_seconds?, timezone?, start_date?, end_date?, mode?...} */
  schedule_config: Record<string, unknown>
  next_run_at?: number | null
  last_run_at?: number | null
  status: 'active' | 'paused'
  created_at?: number
  metadata?: Record<string, unknown>
}

export interface CreateTeamPayload {
  name: string
  description?: string
}

export interface AddTeamMemberPayload {
  agent_id: string
  agent_name?: string
  role?: string
}

export interface CreateTaskPayload {
  name: string
  workflow_id: string
  description?: string
  schedule_config: { type: 'cron' | 'interval' } & Record<string, unknown>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/projects'

/** List all projects. */
export function listProjects() {
  return api.get<ProjectInfo[]>(BASE)
}

/** Get a single project by ID. */
export function getProjectInfo(projectId: string) {
  return api.get<ProjectInfo>(`${BASE}/${projectId}`)
}

/** Create a new project. */
export function createProject(data: { name: string; description?: string }) {
  return api.post<ProjectInfo>(BASE, data)
}

/** Update a project. */
export function updateProject(projectId: string, data: { name?: string; description?: string; status?: string }) {
  return api.put<ProjectInfo>(`${BASE}/${projectId}`, data)
}

/** Delete a project (soft delete). */
export function deleteProject(projectId: string) {
  return api.delete<{ code: number; message: string }>(`${BASE}/${projectId}`)
}

/** Get project stats (team/task/workflow counts). */
export function getProjectStats(projectId: string) {
  return api.get<{
    project_id: string
    teams_count: number
    tasks_count: number
    completed_tasks: number
    active_tasks: number
    workflows_count: number
  }>(`${BASE}/${projectId}/stats`)
}

// ----- 团队 -----

/** List a project's teams. */
export function listProjectTeams(projectId: string) {
  return api.get<{ code: number; data: { teams: ProjectTeamDto[] } }>(`${BASE}/${projectId}/teams`)
}

/** Create a team under a project. */
export function createProjectTeam(projectId: string, data: CreateTeamPayload) {
  return api.post<{ code: number; data: ProjectTeamDto }>(`${BASE}/${projectId}/teams`, data)
}

/** Add an agent to a team. */
export function addTeamMember(projectId: string, teamId: string, data: AddTeamMemberPayload) {
  return api.post<{ code: number; data: ProjectTeamDto }>(`${BASE}/${projectId}/teams/${teamId}/members`, data)
}

/** List a team's agent members. */
export function listTeamAgents(projectId: string, teamId: string) {
  return api.get<{ code: number; data: { agents: { agent_id: string; agent_name?: string; role?: string }[] } }>(
    `${BASE}/${projectId}/teams/${teamId}/agents`,
  )
}

// ----- 任务（定时工作流） -----

/** List a project's scheduled workflow tasks. */
export function listProjectTasks(projectId: string) {
  return api.get<{ code: number; data: { tasks: ProjectTaskDto[] } }>(`${BASE}/${projectId}/tasks`)
}

/** Create a scheduled workflow task (registers APScheduler job). */
export function createProjectTask(projectId: string, data: CreateTaskPayload) {
  return api.post<{ code: number; data: ProjectTaskDto }>(`${BASE}/${projectId}/tasks`, data)
}

/** Pause a scheduled task. */
export function pauseProjectTask(projectId: string, taskId: string) {
  return api.post<{ code: number; data: ProjectTaskDto }>(`${BASE}/${projectId}/tasks/${taskId}/pause`)
}

/** Resume a scheduled task. */
export function resumeProjectTask(projectId: string, taskId: string) {
  return api.post<{ code: number; data: ProjectTaskDto }>(`${BASE}/${projectId}/tasks/${taskId}/resume`)
}

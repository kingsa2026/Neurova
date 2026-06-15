import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Project {
  id: string
  name: string
  description?: string
  status: string
  memberCount?: number
  progress?: number
  activities?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/projects'

/** List all projects. */
export function listProjects() {
  return api.get<Project[]>(BASE)
}

/** Get a single project by ID. */
export function getProject(projectId: string) {
  return api.get<Project>(`${BASE}/${projectId}`)
}

/** Create a new project. */
export function createProject(data: { name: string; description?: string; status?: string }) {
  return api.post<Project>(BASE, data)
}

/** Update a project. */
export function updateProject(projectId: string, data: { name?: string; description?: string; status?: string }) {
  return api.put<Project>(`${BASE}/${projectId}`, data)
}

/** Delete a project. */
export function deleteProject(projectId: string) {
  return api.delete<null>(`${BASE}/${projectId}`)
}

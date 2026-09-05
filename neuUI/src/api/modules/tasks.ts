import { request } from '@/api'

const defaultProject = 'default'

export interface BoardCreate {
  board_id: string
  name: string
  description?: string
  created_by?: string
}

export interface TaskCreate {
  board_id: string
  title: string
  description?: string
  reporter_id?: string
  status?: string
  priority?: string
  assignee_id?: string
  tags?: string[]
  due_date?: string
}

export interface TaskUpdate {
  title?: string
  description?: string
  status?: string
  priority?: string
  assignee_id?: string
  tags?: string[]
  order?: number
}

export interface TaskMove {
  task_id: string
  new_status: string
  new_order?: number
}

export const tasksAPI = {
  listBoards: (projectId = defaultProject) =>
    request.get(`/projects/${projectId}/tasks/boards`),
  createBoard: (data: BoardCreate, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/tasks/boards`, data),
  getBoard: (boardId: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/tasks/boards/${boardId}`),
  getBoardStats: (boardId: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/tasks/${boardId}/stats`),

  createTask: (data: TaskCreate, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/tasks`, data),
  updateTask: (taskId: string, boardId: string, data: TaskUpdate, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/tasks/${taskId}`, { ...data, board_id: boardId }),
  moveTask: (boardId: string, data: TaskMove, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/tasks/${boardId}/move`, data),
}

import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Board {
  id: string
  name: string
}

export interface Task {
  id: string
  title: string
  description: string
  status: string
  priority?: string
  assignee?: string
  dueDate?: string
}

export interface CreateTaskPayload {
  title: string
  description?: string
  priority?: string
  assignee?: string
  dueDate?: string
  status?: string
}

export interface MoveTaskPayload {
  status: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/tasks'

/** List all boards. */
export function listBoards() {
  return api.get<Board[]>(`${BASE}/boards`)
}

/** List tasks for a board. */
export function listBoardTasks(boardId: string) {
  return api.get<Task[]>(`${BASE}/boards/${boardId}/tasks`)
}

/** Create a task in a board. */
export function createTask(boardId: string, data: CreateTaskPayload) {
  return api.post<Task>(`${BASE}/boards/${boardId}/tasks`, data)
}

/** Move a task to a new status. */
export function moveTask(taskId: string, data: MoveTaskPayload) {
  return api.put<Task>(`${BASE}/tasks/${taskId}/move`, data)
}

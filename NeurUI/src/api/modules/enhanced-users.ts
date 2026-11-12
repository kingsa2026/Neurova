import api from '@/api'

// ---------------------------------------------------------------------------
// Types —— 契约与真账本（users.db：int 主键 + status→active 映射）对齐
// ---------------------------------------------------------------------------

export interface User {
  id: number
  username: string
  email?: string
  role?: string
  active?: boolean
  created_at?: string
  last_login?: string
}

export interface UserListParams {
  page?: number
  page_size?: number
  search?: string
}

export interface UserListResponse {
  items?: User[]
  total?: number
}

export interface CreateUserPayload {
  username: string
  email?: string
  password?: string
  role?: string
  active?: boolean
}

export interface UpdateUserPayload {
  email?: string
  role?: string
  active?: boolean
}

export interface UpdatePasswordPayload {
  password: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/enhanced-users'

/** List users with optional pagination and search. */
export function listUsers(params?: UserListParams) {
  return api.get<UserListResponse>(BASE, { params })
}

/** Create a new user（账号立即可走登录链路）. */
export function createUser(data: CreateUserPayload) {
  return api.post<User>(BASE, data)
}

/** Update a user's profile fields. */
export function updateUser(id: number, data: UpdateUserPayload) {
  return api.put<User>(`${BASE}/${id}`, data)
}

/** Delete a user（自删 409：不能删除当前登录账号）. */
export function deleteUser(id: number) {
  return api.delete<null>(`${BASE}/${id}`)
}

/** Update a user's password（管理员重置，哈希落真账本）. */
export function updatePassword(id: number, data: UpdatePasswordPayload) {
  return api.put<null>(`${BASE}/${id}/password`, data)
}

/** Export all users as sanitized JSON blob（不含任何口令材料）. */
export function backupUsers() {
  return api.get<Blob>(`${BASE}/backup`, { responseType: 'blob' })
}

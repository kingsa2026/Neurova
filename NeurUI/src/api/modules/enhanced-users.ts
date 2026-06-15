import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface User {
  id: string
  username: string
  email?: string
  role?: string
  active?: boolean
  quota_used?: number
  quota_limit?: number | string
}

export interface UserListParams {
  page?: number
  page_size?: number
  search?: string
}

export interface UserListResponse {
  items?: User[]
  users?: User[]
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

/** Create a new user. */
export function createUser(data: CreateUserPayload) {
  return api.post<User>(BASE, data)
}

/** Update a user's profile fields. */
export function updateUser(id: string, data: UpdateUserPayload) {
  return api.put<User>(`${BASE}/${id}`, data)
}

/** Delete a user. */
export function deleteUser(id: string) {
  return api.delete<null>(`${BASE}/${id}`)
}

/** Update a user's password. */
export function updatePassword(id: string, data: UpdatePasswordPayload) {
  return api.put<null>(`${BASE}/${id}/password`, data)
}

/** Backup all users as a downloadable blob. */
export function backupUsers() {
  return api.get<Blob>(`${BASE}/backup`, { responseType: 'blob' })
}

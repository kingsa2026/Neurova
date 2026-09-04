import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Group {
  /** 后端契约字段（GroupInfo.group_id） */
  group_id: string
  name: string
  description?: string
  members?: string[]
  members_count?: number
  /** 可用功能模块（菜单路由 key）；空数组 = 不限制 */
  allowed_modules?: string[]
  is_system?: boolean
}

export interface GroupMember {
  id: string
  username: string
  role?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/groups'

/** List all groups. */
export function listGroups() {
  return api.get<Group[]>(BASE)
}

/** Get a single group by ID. */
export function getGroup(groupId: string) {
  return api.get<Group>(`${BASE}/${groupId}`)
}

/** Create a new group. */
export function createGroup(data: { name: string; description?: string; allowed_modules?: string[] }) {
  return api.post<Group>(BASE, data)
}

/** Update a group. */
export function updateGroup(
  groupId: string,
  data: { name?: string; description?: string; allowed_modules?: string[] },
) {
  return api.put<Group>(`${BASE}/${groupId}`, data)
}

/** Delete a group. */
export function deleteGroup(groupId: string) {
  return api.delete<null>(`${BASE}/${groupId}`)
}

/** List members of a group. */
export function listGroupMembers(groupId: string) {
  return api.get<GroupMember[]>(`${BASE}/${groupId}/members`)
}

/** Add a member to a group (by username). */
export function addGroupMember(groupId: string, data: { username: string }) {
  return api.post<null>(`${BASE}/${groupId}/members`, data)
}

/** Remove a member from a group (by username). */
export function removeGroupMember(groupId: string, username: string) {
  return api.delete<null>(`${BASE}/${groupId}/members/${encodeURIComponent(username)}`)
}

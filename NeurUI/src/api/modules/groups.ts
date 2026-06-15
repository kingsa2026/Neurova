import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Group {
  id: string
  name: string
  description?: string
  members_count?: number
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
export function createGroup(data: { name: string; description?: string }) {
  return api.post<Group>(BASE, data)
}

/** Update a group. */
export function updateGroup(groupId: string, data: { name?: string; description?: string }) {
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

/** Add a member to a group. */
export function addGroupMember(groupId: string, data: { username: string }) {
  return api.post<null>(`${BASE}/${groupId}/members`, data)
}

/** Remove a member from a group. */
export function removeGroupMember(groupId: string, memberId: string) {
  return api.delete<null>(`${BASE}/${groupId}/members/${memberId}`)
}

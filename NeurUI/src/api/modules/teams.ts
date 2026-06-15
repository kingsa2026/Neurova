import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Team {
  id: string
  name: string
  description?: string
  members?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/teams'

/** List all teams. */
export function listTeams() {
  return api.get<Team[]>(BASE)
}

/** Get a single team by ID. */
export function getTeam(teamId: string) {
  return api.get<Team>(`${BASE}/${teamId}`)
}

/** Create a new team. */
export function createTeam(data: { name: string; description?: string }) {
  return api.post<Team>(BASE, data)
}

/** Update a team. */
export function updateTeam(teamId: string, data: { name?: string; description?: string }) {
  return api.put<Team>(`${BASE}/${teamId}`, data)
}

/** Delete a team. */
export function deleteTeam(teamId: string) {
  return api.delete<null>(`${BASE}/${teamId}`)
}

/** Add members to a team. */
export function addTeamMembers(teamId: string, data: { members: string[]; prompt?: string }) {
  return api.post<null>(`${BASE}/${teamId}/members`, data)
}

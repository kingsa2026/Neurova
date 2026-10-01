import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ScreenshotResult {
  url?: string
  image?: string
  base64?: string
}

export interface ShellResult {
  output?: string
  result?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/computer'

/** Take a screenshot of the agent's desktop. */
export function screenshot(agentId: string) {
  return api.post<ApiResponse<ScreenshotResult>>(`${BASE}/screenshot`, { agent_id: agentId })
}

/** Click at coordinates on the agent's desktop. */
export function click(agentId: string, x: number, y: number) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}/click`, { agent_id: agentId, x, y })
}

/** Type text on the agent's desktop. */
export function type(agentId: string, text: string) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}/type`, { agent_id: agentId, text })
}

/** Scroll on the agent's desktop. */
export function scroll(agentId: string, direction: string, amount: number) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}/scroll`, { agent_id: agentId, direction, amount })
}

/** Navigate the agent's browser to a URL. */
export function navigate(agentId: string, url: string) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}/browser/navigate`, { agent_id: agentId, url })
}

/** Extract content from the agent's current browser page. */
export function extractPage(agentId: string) {
  return api.post<ApiResponse<unknown>>(`${BASE}/browser/extract`, { agent_id: agentId })
}

/** Semantic click: resolve the target against current snapshot facts on the server.
 *  `ref` is the second addressing entry: after a 409 the response lists the ambiguous
 *  candidates with their snapshot-bound ids (e1/e2...), and resending with one of them
 *  clicks exactly that element. */
export function smartClick(target: string, ref = '') {
  return api.post<ApiResponse<{ success: boolean; matched: { role?: string; name?: string; ref?: string } }>>(
    `${BASE}/smart-click`, { target, ref })
}

/** Semantic type: same resolution and same ref escape hatch as smartClick. */
export function smartType(target: string, text: string, ref = '') {
  return api.post<ApiResponse<{ success: boolean; matched: { role?: string; name?: string; ref?: string } }>>(
    `${BASE}/smart-type`, { target, text, ref })
}

/** Execute a shell command on the agent's machine. */
export function shell(agentId: string, command: string) {
  return api.post<ApiResponse<ShellResult>>(`${BASE}/shell`, { agent_id: agentId, command })
}

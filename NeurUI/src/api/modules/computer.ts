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

/** Smart-click at coordinates using AI element detection. */
export function smartClick(agentId: string, x: number, y: number) {
  return api.post<ApiResponse<{ success: boolean }>>(`${BASE}/smart-click`, { agent_id: agentId, x, y })
}

/** Parse the agent's current screen visually. */
export function visualParse(agentId: string) {
  return api.post<ApiResponse<unknown>>(`${BASE}/visual-parse`, { agent_id: agentId })
}

/** Execute a shell command on the agent's machine. */
export function shell(agentId: string, command: string) {
  return api.post<ApiResponse<ShellResult>>(`${BASE}/shell`, { agent_id: agentId, command })
}

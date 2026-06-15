import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MCPServer {
  id: string
  name: string
  url: string
  status: string
  tool_count?: number
  auth_token?: string
}

export interface Tool {
  id: string
  name: string
  description?: string
  type: string
  enabled?: boolean
  public?: boolean
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/tool-layers'

/** List all registered MCP servers. */
export function listMCPServers() {
  return api.get<MCPServer[]>(`${BASE}/mcp-servers`)
}

/** List all available tools. */
export function listTools() {
  return api.get<Tool[]>(`${BASE}/tools`)
}

/** Register a new MCP server. */
export function registerMCPServer(data: { name: string; url: string; auth_token?: string }) {
  return api.post<MCPServer>(`${BASE}/mcp-servers`, data)
}

/** Unregister an MCP server. */
export function unregisterMCPServer(id: string) {
  return api.delete<null>(`${BASE}/mcp-servers/${id}`)
}

/** Test an MCP server connection. */
export function testMCPServer(id: string) {
  return api.post<null>(`${BASE}/mcp-servers/${id}/test`)
}

/** Install a tool by ID. */
export function installTool(toolId: string) {
  return api.post<null>(`${BASE}/tools/install`, { tool_id: toolId })
}

/** Execute a tool with parameters. */
export function executeTool(toolId: string, params: Record<string, unknown>) {
  return api.post<unknown>(`${BASE}/tools/${toolId}/execute`, params)
}

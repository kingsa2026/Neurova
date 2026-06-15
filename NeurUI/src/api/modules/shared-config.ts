import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LLMProvider {
  id: string
  name: string
  type: 'openai' | 'anthropic' | 'azure' | 'local' | 'custom'
  base_url: string
  api_key?: string
  models: string[]
  enabled: boolean
  config?: Record<string, unknown>
  created_at?: string
}

export interface MCPServer {
  id: string
  name: string
  type: 'stdio' | 'sse' | 'http'
  command?: string
  args?: string[]
  url?: string
  headers?: Record<string, string>
  enabled: boolean
  tools_count?: number
  status?: 'connected' | 'disconnected' | 'error'
  config?: Record<string, unknown>
  created_at?: string
}

export interface ProviderCreatePayload {
  name: string
  type: string
  base_url: string
  api_key?: string
  models?: string[]
  config?: Record<string, unknown>
}

export interface MCPServerCreatePayload {
  name: string
  type: string
  command?: string
  args?: string[]
  url?: string
  headers?: Record<string, string>
  config?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// API – LLM Providers
// ---------------------------------------------------------------------------

const BASE = '/shared-config'

/** List all LLM providers. */
export function getProviders() {
  return api.get<ApiResponse<LLMProvider[]>>(`${BASE}/llm-providers`)
}

/** Get a single provider. */
export function getProvider(id: string) {
  return api.get<ApiResponse<LLMProvider>>(`${BASE}/llm-providers/${id}`)
}

/** Create a new LLM provider. */
export function createProvider(data: ProviderCreatePayload) {
  return api.post<ApiResponse<LLMProvider>>(`${BASE}/llm-providers`, data)
}

/** Update a provider. */
export function updateProvider(id: string, data: Partial<ProviderCreatePayload>) {
  return api.put<ApiResponse<LLMProvider>>(`${BASE}/llm-providers/${id}`, data)
}

/** Delete a provider. */
export function deleteProvider(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/llm-providers/${id}`)
}

/** Test a provider connection. */
export function testProvider(id: string) {
  return api.post<ApiResponse<{ success: boolean; latency_ms: number; error?: string }>>(`${BASE}/llm-providers/${id}/test`)
}

// ---------------------------------------------------------------------------
// API – MCP Servers
// ---------------------------------------------------------------------------

/** List all MCP servers. */
export function getMCPServers() {
  return api.get<ApiResponse<MCPServer[]>>(`${BASE}/mcp-servers`)
}

/** Get a single MCP server. */
export function getMCPServer(id: string) {
  return api.get<ApiResponse<MCPServer>>(`${BASE}/mcp-servers/${id}`)
}

/** Create a new MCP server. */
export function createMCPServer(data: MCPServerCreatePayload) {
  return api.post<ApiResponse<MCPServer>>(`${BASE}/mcp-servers`, data)
}

/** Update an MCP server. */
export function updateMCPServer(id: string, data: Partial<MCPServerCreatePayload>) {
  return api.put<ApiResponse<MCPServer>>(`${BASE}/mcp-servers/${id}`, data)
}

/** Delete an MCP server. */
export function deleteMCPServer(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/mcp-servers/${id}`)
}

/** Test an MCP server connection. */
export function testMCPServer(id: string) {
  return api.post<ApiResponse<{ success: boolean; tools_count: number; error?: string }>>(`${BASE}/mcp-servers/${id}/test`)
}

// ---------------------------------------------------------------------------
// API – Export / Import
// ---------------------------------------------------------------------------

/** Export all shared config (providers + MCP servers). */
export function exportConfig() {
  return api.get<ApiResponse<{ providers: LLMProvider[]; mcp_servers: MCPServer[] }>>(`${BASE}/export`)
}

/** Import shared config. */
export function importConfig(data: { providers?: Partial<ProviderCreatePayload>[]; mcp_servers?: Partial<MCPServerCreatePayload>[] }) {
  return api.post<ApiResponse<{ imported_providers: number; imported_servers: number }>>(`${BASE}/import`, data)
}

import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MCPServer {
  // 契约对齐（2026-09-12 复核）：后端 MCPServerInfo 实际字段为 server_id/tools_count，
  // 旧 interface 的 id/tool_count 恒 undefined（servers 卡片 key/测试/删除全打空）。
  server_id: string
  name: string
  url: string
  transport: string
  status: string
  tools_count?: number
  auth_token?: string
  oauth_grant?: string | null
}

export interface Tool {
  id: string
  name: string
  description?: string
  type: string
  enabled?: boolean
  public?: boolean
  /** P2-15 声明位：true=工具声明必须在沙箱下执行（后端 builtin_tools schema） */
  sandbox_required?: boolean | null
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
/**
 * register 弹窗载荷构造（纯函数，契约测试锁定）——2026-09-12 复核修复：
 * ① transport 必须显式 http（后端默认 stdio → 校验要求 command → 恒 400）；
 * ② auth_token 映射为标准 Bearer Authorization 头（此前被直接丢弃 → 输入框
 *    不起作用）；空值不发，不污染配置。headers 经 connect 端点入持久化配置，
 *    协议层 _open_session（httpx/sse_client）真实消费。
 */
export function buildMCPRegisterPayload(
  name: string,
  url: string,
  authToken?: string,
): { name: string; url: string; transport: string; headers: Record<string, string> } {
  const payload = { name, url, transport: "http", headers: {} as Record<string, string> }
  const token = (authToken || "").trim()
  if (token) {
    payload.headers.Authorization = `Bearer ${token}`
  }
  return payload
}

export function registerMCPServer(data: { name: string; url: string; auth_token?: string }) {
  return api.post<MCPServer>(
    `${BASE}/mcp-servers`,
    buildMCPRegisterPayload(data.name, data.url, data.auth_token),
  )
}

/** Unregister an MCP server. */
export function unregisterMCPServer(id: string) {
  return api.delete<null>(`${BASE}/mcp-servers/${id}`)
}

/** Run the OAuth2 authorization-code flow for an MCP server (opens the browser, waits for loopback callback). */
export function authorizeMCPOAuth(id: string) {
  // 授权等待用户在浏览器完成操作，可能远超全局 apiTimeout（300s）
  return api.post<{ status: string; server_id: string; token_hint?: string }>(
    `${BASE}/mcp-servers/${id}/oauth/authorize`,
    {},
    { timeout: 370000 },
  )
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

// ---------------------------------------------------------------------------
// MCP 白名单目录（P0-2）
// ---------------------------------------------------------------------------

export interface MCPCatalogEntry {
  id: string
  name: string
  description: string
  source: string
  transport: string
  command: string
  args: string[]
  requires?: string | null
  required_secrets: Array<{
    key: string
    required: boolean
    into: string
    prompt: string
    read_only_required?: boolean
  }>
}

/** List curated MCP tool packages (no install side effect). */
export function listMCPCatalog() {
  return api.get<MCPCatalogEntry[]>(`${BASE}/mcp-catalog`)
}

/** One-click install a curated MCP package with its secrets. */
export function installMCPCatalogEntry(entryId: string, secrets: Record<string, string>) {
  return api.post<MCPServer>(`${BASE}/mcp-catalog/${entryId}/install`, { secrets })
}

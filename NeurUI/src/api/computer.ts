import api from '@/api'
import type { Computer } from '@/types/computer'

// ---------------------------------------------------------------------------
// 计算节点（Computer）客户端
//
// 走 `@/api` 的**唯一 axios 实例**（`src/api/index.ts`）：Bearer token 注入、
// 401 单飞刷新、响应信封解包与 X-Request-ID 全在那一处。此前本文件自建裸
// 裸 axios 实例并把基地址硬编码成 `/api` —— 无 token、无信封解包，
// 且指向当时未挂载的 `/api/computers`，三个缺陷叠在同一个文件里。
//
// 后端面：`neurova/api/endpoints/computer_api.py`（挂载点 `/api/v1/computers`，
// 身份取自真实 JWT）。成本读取面**不在此文件**——唯一事实源是
// `@/api/modules/cost`（`/api/v1/cost-rollup/*` 与 `/api/v1/budgets/*`）。
// ---------------------------------------------------------------------------

const BASE = '/computers'

export type ComputerKind = 'cloud' | 'local' | 'vps'

export interface CreateComputerParams {
  name: string
  kind?: ComputerKind
  engine?: string
  company_id?: string
}

export interface PairByOaParams {
  pair_token: string
  host_name: string
  available_engines: string[]
  daemon_version: string
  supervised?: boolean
}

/** 获取当前用户的所有 Computers */
export function listUserComputers(): Promise<Computer[]> {
  return api.get<Computer[]>(BASE)
}

/** 创建新 Computer */
export function createComputer(params: CreateComputerParams): Promise<Computer> {
  return api.post<Computer>(BASE, undefined, { params })
}

/** 获取指定 Computer */
export function getComputer(computerId: string): Promise<Computer> {
  return api.get<Computer>(`${BASE}/${encodeURIComponent(computerId)}`)
}

/** 删除 Computer */
export function deleteComputer(computerId: string, hard = false): Promise<void> {
  return api.delete<void>(`${BASE}/${encodeURIComponent(computerId)}`, { params: { hard } })
}

/** BYOA Computer 配对 */
export function pairByOAComputer(computerId: string, params: PairByOaParams): Promise<Computer> {
  return api.post<Computer>(`${BASE}/${encodeURIComponent(computerId)}/pair`, params)
}

/** 撤销 Computer 访问 */
export function revokeComputer(computerId: string): Promise<Computer> {
  return api.post<Computer>(`${BASE}/${encodeURIComponent(computerId)}/revoke`)
}

/** 发送 heartbeat */
export function heartbeat(computerId: string, version?: string): Promise<{ status: string }> {
  return api.post<{ status: string }>(
    `${BASE}/${encodeURIComponent(computerId)}/heartbeat`,
    {},
    { params: { version } },
  )
}

/** 列出 Computer 上的 Agents */
export function listAgentsOnComputer(computerId: string): Promise<string[]> {
  return api.get<string[]>(`${BASE}/${encodeURIComponent(computerId)}/agents`)
}

/** 获取 Cloud Computer */
export function getCloudComputer(companyId?: string): Promise<Computer> {
  return api.get<Computer>(`${BASE}/cloud`, { params: { company_id: companyId } })
}

/** 清理离线 Computers */
export function cleanupOfflineComputers(timeoutMinutes = 90): Promise<{ cleaned_count: number }> {
  return api.post<{ cleaned_count: number }>(`${BASE}/cleanup-offline`, {}, {
    params: { timeout_minutes: timeoutMinutes },
  })
}

/** 兼容聚合导出：旧调用点按 `computerApi.xxx` 组织（无 `costApi`——成本面见 `@/api/modules/cost`）。 */
export const computerApi = {
  listUserComputers,
  createComputer,
  getComputer,
  deleteComputer,
  pairByOAComputer,
  revokeComputer,
  heartbeat,
  listAgentsOnComputer,
  getCloudComputer,
  cleanupOfflineComputers,
}

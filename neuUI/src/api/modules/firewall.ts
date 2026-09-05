import { request } from '@/api'

export interface GlobalRulesRequest {
  blocked_extensions?: string[]
  blocked_paths?: string[]
  blocked_patterns?: string[]
  rate_limit_per_minute?: number
  max_payload_bytes?: number
  ip_whitelist?: string[]
  ip_blacklist?: string[]
}

export interface UserRulesRequest {
  extra_blocked_extensions?: string[]
  extra_blocked_paths?: string[]
}

export interface SandboxRequest {
  agent_isolation: boolean
}

export interface CheckPathRequest {
  path: string
}

export const firewallAPI = {
  getGlobalRules: () => request.get('/firewall/global'),
  updateGlobalRules: (data: GlobalRulesRequest) =>
    request.put('/firewall/global', data),
  getUserRules: () => request.get('/firewall/user/rules'),
  updateUserRules: (data: UserRulesRequest) =>
    request.put('/firewall/user/rules', data),
  updateSandbox: (data: SandboxRequest) =>
    request.put('/firewall/user/sandbox', data),
  listAllUsers: () => request.get('/firewall/admin/users'),
  checkPath: (data: CheckPathRequest) =>
    request.post('/firewall/check', data),
}

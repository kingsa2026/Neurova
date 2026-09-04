import api from '@/api'

// ---------------------------------------------------------------------------
// Types — Agent 应用包（P2-16，Claw 式一清单收敛）
// ---------------------------------------------------------------------------

export interface AgentPackageManifest {
  kind: 'neurova.agent-package'
  manifest_version: number
  agent: {
    name: string
    description?: string
    model?: string
    provider?: string
    personality?: string
    constitution?: string
  }
  skills: Array<{
    id: string
    name: string
    version: string
    description?: string
    enabled?: boolean
  }>
  cron: Array<{
    name: string
    description?: string
    action: string
    cron_expression?: string | null
    interval_seconds?: number | null
    scheduled_at?: number | null
    parameters?: Record<string, unknown>
  }>
  mcp: Array<{
    id: string
    name: string
    transport?: string
    description?: string
    enabled?: boolean
  }>
  provenance: {
    exported_at: string
    source: string
    package_version: number
    agent_id?: string
  }
}

export interface AgentPackageImportResult {
  success: boolean
  agent_id: string
  imported: { skills: string[]; cron: number; mcp: number }
  manifest_version: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

/** 导出 agent 应用包（manifest v1 JSON）。 */
export function exportAgentPackage(agentId: string) {
  return api.get<AgentPackageManifest>(`/agents/${agentId}/export-package`)
}

/** 导入 agent 应用包。 */
export function importAgentPackage(payload: {
  manifest: AgentPackageManifest
  agent_id: string
  import_skills: boolean
  import_cron: boolean
  import_mcp: boolean
}) {
  return api.post<AgentPackageImportResult>('/agents/import-package', payload)
}

/** 触发浏览器下载导出的 manifest JSON（Blob 模式，对齐 KnowledgePage 导出先例）。 */
export function downloadManifest(manifest: AgentPackageManifest, agentId: string) {
  const blob = new Blob([JSON.stringify(manifest, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-package-${agentId}.json`
  a.click()
  URL.revokeObjectURL(url)
}

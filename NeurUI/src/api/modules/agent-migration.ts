import api from '@/api'

export interface AgentMigrationImportResult {
  success: boolean
  agent_id: string
  source_agent_id: string
  overwritten: boolean
  owner_user_id: string
  imported: { skills: string[]; cron: number; mcp: number }
  manifest_version: number
}

/** 导出 agent 完整迁移包（zip）。 */
export function exportAgentMigration(agentId: string): Promise<Blob> {
  return api.get<Blob>(`/agents/${agentId}/export-migration`, { responseType: 'blob' })
}

/** 触发浏览器下载迁移包 zip。 */
export function downloadMigrationZip(blob: Blob, agentId: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-migration-${agentId}.zip`
  a.click()
  URL.revokeObjectURL(url)
}

/** 导入 agent 迁移包。归属由后端写成导入者。 */
export function importAgentMigration(
  file: File,
  payload: {
    agent_id: string
    overwrite: boolean
    import_skills: boolean
    import_cron: boolean
    import_mcp: boolean
  },
) {
  const form = new FormData()
  form.append('file', file)
  form.append('agent_id', payload.agent_id)
  form.append('overwrite', String(payload.overwrite))
  form.append('import_skills', String(payload.import_skills))
  form.append('import_cron', String(payload.import_cron))
  form.append('import_mcp', String(payload.import_mcp))
  return api.post<AgentMigrationImportResult>('/agents/import-migration', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
